"""Paper metadata: page-1 heuristics on synthetic one-page PDFs, CrossRef / arXiv with fake HTTP.

No network, no real PDF: pages are drawn with pymupdf insert_text, requests is monkeypatched.
Run:  python -m pytest tests/test_metadata.py -q
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from pdf2word import __version__  # noqa: E402
from pdf2word import metadata as M  # noqa: E402
from pdf2word.obsidian import ensure_title  # noqa: E402

_HELV = pymupdf.Font("helv")


# ----------------------------------------------------------------------------- helpers

class FakeResp:
    def __init__(self, status=200, json_data=None, text=""):
        self.status_code = status
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _fake_http(monkeypatch, handler):
    """Route every requests call (requests.get and Session.get) to handler(url, params)."""
    calls = []

    def request(self, method, url, params=None, headers=None, timeout=None, **kw):
        calls.append({"session": id(self), "url": url, "params": dict(params or {}),
                      "headers": dict(headers or {})})
        return handler(url, params or {})

    monkeypatch.setattr(requests.sessions.Session, "request", request)
    return calls


def _crossref(records):
    """Handler answering CrossRef /works/<doi> from {doi: message}, 404 otherwise."""
    def handler(url, params):
        if "api.crossref.org" in url:
            doi = requests.utils.unquote(url.rsplit("/", 1)[1])
            if doi in records:
                return FakeResp(200, {"message": records[doi]})
        return FakeResp(404)
    return handler


def _crossref_dois(calls):
    return [requests.utils.unquote(c["url"].rsplit("/", 1)[1]) for c in calls if "crossref" in c["url"]]


def _blank_doc():
    doc = pymupdf.open()
    doc.new_page()
    return doc


def _words(page, x, y, words, size, gap_em=0.5):
    """Words drawn one by one with a gap and no space glyph (MuPDF then makes ' ' spans)."""
    for w in words:
        page.insert_text((x, y), w, fontsize=size)
        x += _HELV.text_length(w, size) + gap_em * size


def _runs(page, x, y, parts):
    """One line of (text, size, rise) runs: rise > 0 raises the run (superscript)."""
    for text, size, rise in parts:
        page.insert_text((x, y - rise), text, fontsize=size)
        x += _HELV.text_length(text, size)


# ----------------------------------------------------------------------------- #32 spaces as spans

def test_page_lines_keeps_synthetic_spaces():
    doc = pymupdf.open()
    page = doc.new_page()
    _words(page, 72, 120, "Heat transfer in spiral jet mills".split(), 18)
    _words(page, 72, 150, ["John", "Smith,", "Maria", "Garcia"], 11)
    raw = page.get_text("dict")["blocks"][0]["lines"][0]["spans"]
    assert any(s["text"] == " " for s in raw)          # the fixture really has space-only spans
    assert M._page_lines(page)[0][2] == "Heat transfer in spiral jet mills"
    meta = M.heuristic_meta(doc, page.get_text("text"))
    assert meta.title == "Heat transfer in spiral jet mills"
    assert meta.authors == ["John Smith", "Maria Garcia"]
    assert meta.first_author == "Smith"


# ----------------------------------------------------------------------------- #33 keywords

@pytest.mark.parametrize("text, expected", [
    # A: Elsevier article-info box, one keyword per line, spaced 'a b s t r a c t' heading
    ("A R T I C L E  I N F O\nArticle history:\nReceived 3 May 2013\nKeywords:\nSpiral jet mill\nCFD\nDEM\n"
     "Particle breakage\nClassification\nCut size\na b s t r a c t\nThis paper studies the grinding of powders.\n",
     ["Spiral jet mill", "CFD", "DEM", "Particle breakage", "Classification", "Cut size"]),
    # B: separated list starting on the next line, wrapped
    ("Keywords:\nspiral jet mill; computational fluid dynamics;\nparticle breakage; cut size\n\n1. Introduction\n",
     ["spiral jet mill", "computational fluid dynamics", "particle breakage", "cut size"]),
    # E: one per line, body text follows without a heading -> stop at the first non-keyword line
    ("Keywords:\nJet mill\nBreakage\nThe mill was run at 6 bar.\nResults are shown\nin Fig. 2 and Table 1 for all\n",
     ["Jet mill", "Breakage"]),
    # F: one per line, then a plain 'Abstract' heading
    ("Keywords:\nJet mill\nBreakage\nAbstract\nWe study mills.\n", ["Jet mill", "Breakage"]),
    # G: one per line, then body text with commas (must not switch to the separated-list mode)
    ("Keywords:\nJet mill\nBreakage\nIn this work, we study the grinding of\npowders in a mill.\n",
     ["Jet mill", "Breakage"]),
    # controls: same line as 'Keywords:' (unchanged behaviour)
    ("Keywords: spiral jet mill, CFD, DEM\n\n1. Introduction\n", ["spiral jet mill", "CFD", "DEM"]),
    ("Keywords: spiral jet mill; computational fluid\ndynamics; DEM\n\n1. Introduction\n",
     ["spiral jet mill", "computational fluid dynamics", "DEM"]),
    ("Keywords: spiral jet mill  CFD  DEM\n\n1. Introduction\n", ["spiral jet mill", "CFD", "DEM"]),
    ("Keywords: Spiral jet mill.\n\n1. Introduction\n", ["Spiral jet mill"]),
], ids=["A-elsevier-one-per-line", "B-wrapped-next-line", "E-body-follows", "F-abstract-heading",
        "G-body-with-commas", "C-same-line", "D-same-line-wrapped", "H-double-spaces", "I-single-with-period"])
def test_keywords_one_per_line(text, expected):
    assert M.heuristic_meta(_blank_doc(), text).keywords == expected


# ----------------------------------------------------------------------------- #34 CrossRef markup

def test_crossref_title_markup(monkeypatch):
    records = {
        "10.1000/test.1": {
            "title": ["Effect of <i>in situ</i> grinding on H<sub>2</sub>O uptake in <scp>MOF</scp> powders"],
            "container-title": ["Industrial &amp; Engineering Chemistry Research"],
            "DOI": "10.1000/test.1"},
        "10.1000/aps.2": {"title": ["Superconductivity in<i>p</i>-wave films of Sr<sub>2</sub>RuO<sub>4</sub>"]},
        "10.1000/lit.3": {"title": ["When a < b > c holds for <b>all</b> mills"]},
    }
    _fake_http(monkeypatch, _crossref(records))
    meta = M.crossref_lookup("10.1000/test.1")
    assert meta.title == "Effect of in situ grinding on H2O uptake in MOF powders"
    assert meta.journal == "Industrial & Engineering Chemistry Research"
    assert M.crossref_lookup("10.1000/aps.2").title == "Superconductivity in p-wave films of Sr2RuO4"
    assert M.crossref_lookup("10.1000/lit.3").title == "When a < b > c holds for all mills"
    body = "# Effect of in situ grinding on H2O uptake in MOF powders\n\nText.\n"
    out = ensure_title(body, meta.title)
    assert sum(1 for line in out.split("\n") if line.startswith("# ")) == 1


# ----------------------------------------------------------------------------- #35 masthead, superscripts

def _elsevier_page():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 50), "International Journal of Heat and Mass Transfer 70 (2014) 123-135", fontsize=7)
    page.insert_text((200, 68), "Contents lists available at ScienceDirect", fontsize=8)
    page.insert_text((130, 92), "International Journal of Heat and Mass Transfer", fontsize=14.22)
    page.insert_text((180, 108), "journal homepage: www.elsevier.com/locate/ijhmt", fontsize=8)
    page.insert_text((72, 150), "Large eddy simulation of the swirling flow in a", fontsize=13.45)
    page.insert_text((72, 166), "spiral jet mill with particle breakage", fontsize=13.45)
    _runs(page, 72, 190, [("John Smith", 10, 0), ("a", 6.5, 4), (", Maria Garcia", 10, 0),
                          ("b,", 6.5, 4), ("*", 6.5, 4)])
    page.insert_text((72, 210), "a Department of Mechanical Engineering, Example University, City", fontsize=7)
    page.insert_text((72, 218), "b Institute of Process Engineering, Example Institute, City", fontsize=7)
    return doc


def test_elsevier_masthead_and_superscripts():
    doc = _elsevier_page()
    spans = [s for b in doc[0].get_text("dict")["blocks"] for line in b["lines"] for s in line["spans"]]
    assert any(s["text"] == "a" and s["flags"] & 1 for s in spans)      # fixture: raised = superscript
    meta = M.heuristic_meta(doc, doc[0].get_text("text"))
    assert meta.title == "Large eddy simulation of the swirling flow in a spiral jet mill with particle breakage"
    assert meta.authors == ["John Smith", "Maria Garcia"]
    assert meta.first_author == "Smith"


def test_author_smallcaps_kept():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), "A study of grinding in spiral jet mills", fontsize=16)
    _runs(page, 72, 150, [("J", 10, 0), ("OHN", 7.5, 0), (" S", 10, 0), ("MITH", 7.5, 0), ("a", 6.5, 4)])
    page.insert_text((72, 170), "a Department of Chemistry, Example University", fontsize=8)
    meta = M.heuristic_meta(doc, page.get_text("text"))
    assert meta.authors == ["JOHN SMITH"]


def test_corresponding_marks_stripped():
    assert M.split_author_line("John Smith, Maria Garcia⇑") == ["John Smith", "Maria Garcia"]
    assert M.split_author_line("John Smith⁎, Maria Garcia") == ["John Smith", "Maria Garcia"]


def test_title_keeps_superscripts():
    """Superscripts are dropped from author lines only: the title (which overwrites the body H1) keeps them."""
    doc = pymupdf.open()
    page = doc.new_page()
    _runs(page, 72, 120, [("Uptake of Ca", 16, 0), ("2+", 10, 6), (" ions in porous powders", 16, 0)])
    assert M.heuristic_meta(doc, page.get_text("text")).title == "Uptake of Ca2+ ions in porous powders"


# ----------------------------------------------------------------------------- #36 year

def _two_page_doc(page1_lines, page2_lines=()):
    doc = pymupdf.open()
    for lines in (page1_lines, page2_lines):
        if not lines:
            continue
        page = doc.new_page()
        for i, text in enumerate(lines):
            page.insert_text((72, 60 + 14 * i), text, fontsize=9)
    text = "\n".join(p.get_text("text") for p in doc)
    return doc, text


@pytest.mark.parametrize("page1, page2, expected", [
    # Elsevier: history spans 2012-2013, the volume line on top says 2014
    (["International Journal of Heat and Mass Transfer 70 (2014) 123-135",
      "Article history:", "Received 20 December 2012", "Received in revised form 3 October 2013",
      "Accepted 5 November 2013", "Available online 1 December 2013"], (), 2014),
    # no citation line: the latest date keyword, not the leftmost ('Received')
    (["Received 20 December 2012; accepted 5 November 2013", "Published online 1 December 2013"], (), 2013),
    # a reference-style citation on page 2 is not the paper's own citation line
    (["Received 3 May 2019; accepted 1 June 2019", "Introduction"],
     ["As shown by Smith, Phys. Fluids 12 (2005) 33-45, ..."], 2019),
    # a citation on top of page 1 older than the article history is ignored
    (["As shown by Smith, Phys. Fluids 12 (2005) 33-45", "Received 3 May 2019; accepted 1 June 2019"],
     (), 2019),
], ids=["elsevier-citation-line", "latest-date-keyword", "page2-citation-ignored", "older-citation-ignored"])
def test_heuristic_year_prefers_citation_line(page1, page2, expected):
    doc, text = _two_page_doc(page1, page2)
    assert M.heuristic_meta(doc, text).year == expected


# ----------------------------------------------------------------------------- #37 DOI with parentheses

def test_doi_with_parentheses():
    assert M.find_doi("doi:10.1016/0021-9991(81)90145-5") == "10.1016/0021-9991(81)90145-5"
    assert M.find_doi("(see doi:10.1016/0021-9991(81)90145-5).") == "10.1016/0021-9991(81)90145-5"
    assert M.find_doi("https://doi.org/10.1016/0021-9991(81)90145-5 Elsevier") == "10.1016/0021-9991(81)90145-5"
    assert M.find_doi("J. Comput. Phys. 10.1016/0021-9991(81)90145-5, 1981") == "10.1016/0021-9991(81)90145-5"
    assert M.find_doi("(doi:10.1000/xyz)") == "10.1000/xyz"
    assert M.find_doi("doi:10.1000/abc]") == "10.1000/abc"
    assert M.find_doi("doi:10.1000/abc.Received 3 May") == "10.1000/abc"
    assert M.find_doi("doi:10.1016/j.powtec.2020.01.001.") == "10.1016/j.powtec.2020.01.001"


# ----------------------------------------------------------------------------- #38 compound surnames

@pytest.mark.parametrize("given, family, expected", [
    ("Gabriel", "García Márquez", "García Márquez"),
    ("Siti", "Abu Bakar", "Abu Bakar"),
    ("Ludwig van", "Beethoven", "van Beethoven"),
    ("Jan", "van der Berg", "van der Berg"),
    ("광희", "김", "김"),
])
def test_crossref_first_author_family(monkeypatch, given, family, expected):
    _fake_http(monkeypatch, _crossref({"10.1000/x": {"title": ["T"], "author": [{"given": given, "family": family}]}}))
    assert M.crossref_lookup("10.1000/x").first_author == expected


def test_crossref_first_author_name_only(monkeypatch):
    _fake_http(monkeypatch, _crossref({"10.1000/x": {"title": ["T"], "author": [{"name": "Kwang Hee Kim"}]}}))
    assert M.crossref_lookup("10.1000/x").first_author == "Kim"


# ----------------------------------------------------------------------------- #39 which DOI is the paper's

_RECORDS = {
    "10.5281/zenodo.123456": {"title": ["Dataset: PIV fields of a jet mill"], "DOI": "10.5281/zenodo.123456",
                              "author": [{"given": "Data", "family": "Curator"}],
                              "published-print": {"date-parts": [[2019]]}},
    "10.1000/jfm.2021.77": {"title": ["Breakage of agglomerates in spiral jet mills"], "DOI": "10.1000/jfm.2021.77",
                            "author": [{"given": "Kim", "family": "Lee"}],
                            "published-print": {"date-parts": [[2021]]}},
}


def test_resolve_prefers_doi_matching_page1(monkeypatch):
    calls = _fake_http(monkeypatch, _crossref(_RECORDS))
    page1 = ("Breakage of agglomerates in spiral jet mills\nKim Lee\nAbstract\nWe study breakage. "
             "The measured PIV data are available at doi:10.5281/zenodo.123456.\n"
             "Journal of Fluid Mechanics, https://doi.org/10.1000/jfm.2021.77\n")
    meta = M.resolve_metadata(_blank_doc(), page1, online=True)
    assert _crossref_dois(calls) == ["10.5281/zenodo.123456", "10.1000/jfm.2021.77"]
    assert meta.title == "Breakage of agglomerates in spiral jet mills"
    assert (meta.doi, meta.first_author, meta.year) == ("10.1000/jfm.2021.77", "Lee", 2021)


def test_resolve_keeps_single_doi_when_title_absent(monkeypatch, caplog):
    calls = _fake_http(monkeypatch, _crossref(_RECORDS))
    page1 = "스파이럴 제트밀 내 응집체 파쇄\n이 김\nhttps://doi.org/10.1000/jfm.2021.77\n"
    with caplog.at_level(logging.INFO, logger="pdf2word"):
        meta = M.resolve_metadata(_blank_doc(), page1, online=True)
    assert _crossref_dois(calls) == ["10.1000/jfm.2021.77"]
    assert meta.source == "crossref"
    assert meta.title == "Breakage of agglomerates in spiral jet mills"
    assert any(r.levelno == logging.WARNING and "title not found" in r.getMessage() for r in caplog.records)


def test_find_dois_order():
    text = ("see 10.1000/bare.1 and doi:10.1000/ann.2, https://doi.org/10.1000/ann.3 "
            "10.1000/ann.2 10.1000/bare.4 10.1000/bare.5")
    assert M.find_dois(text) == ["10.1000/ann.2", "10.1000/ann.3", "10.1000/bare.1"]
    assert M.find_dois(text)[0] == M.find_doi(text)
    assert M.find_dois("no identifier") == []


# ----------------------------------------------------------------------------- #40 '&' between authors

def test_split_author_line_ampersand():
    assert M.split_author_line("John Smith & Maria Garcia") == ["John Smith", "Maria Garcia"]
    assert M.split_author_line("J. Smith, K. Lee & M. Garcia") == ["J. Smith", "K. Lee", "M. Garcia"]
    assert M.split_author_line("Huaqing Ma1,§, Changhua Xie2 and Yongzhi Zhao2,✉") == \
        ["Huaqing Ma", "Changhua Xie", "Yongzhi Zhao"]
    assert M.split_author_line("Alexander Anderson") == ["Alexander Anderson"]


# ----------------------------------------------------------------------------- #41 failures are visible

_ARXIV_OK = ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
             'xmlns:arxiv="http://arxiv.org/schemas/atom"><entry><id>http://arxiv.org/abs/2301.12345v2</id>'
             '<published>2023-01-29T00:00:00Z</published><title>Learning grinding fast</title>'
             '<author><name>Ada Lovelace</name></author></entry></feed>')


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("text, handler, expect", [
    ("Title of the paper here\ndoi:10.1000/abc.1\n", lambda u, p: FakeResp(404), "CrossRef 10.1000/abc.1: HTTP 404"),
    ("Title of the paper here\ndoi:10.1000/abc.1\n", lambda u, p: FakeResp(429), "HTTP 429"),
    ("Title of the paper here\narXiv:2301.12345v2 [cs.LG]\n", lambda u, p: FakeResp(503),
     "arXiv 2301.12345: HTTP 503"),
], ids=["crossref-404", "crossref-429", "arxiv-503"])
def test_lookup_failure_logged(monkeypatch, caplog, text, handler, expect):
    _fake_http(monkeypatch, handler)
    with caplog.at_level(logging.INFO, logger="pdf2word"):
        meta = M.resolve_metadata(_blank_doc(), text, online=True)
    assert meta.source == "heuristic"
    warns = _warnings(caplog)
    assert len(warns) == 1 and expect in warns[0] and "heuristics" in warns[0]


def test_lookup_exception_logged(monkeypatch, caplog):
    def boom(url, params):
        raise requests.ConnectionError("ProxyError: blocked")
    _fake_http(monkeypatch, boom)
    with caplog.at_level(logging.INFO, logger="pdf2word"):
        M.resolve_metadata(_blank_doc(), "Title\ndoi:10.1000/abc.1\n", online=True)
    warns = _warnings(caplog)
    assert len(warns) == 1 and "ProxyError" in warns[0]


def test_no_identifier_logs_plain_heuristics(monkeypatch, caplog):
    calls = _fake_http(monkeypatch, lambda u, p: FakeResp(404))
    with caplog.at_level(logging.INFO, logger="pdf2word"):
        M.resolve_metadata(_blank_doc(), "Title of the paper here\nno identifier\n", online=True)
        M.resolve_metadata(_blank_doc(), "Title\ndoi:10.1000/abc.1\n", online=False)
    assert calls == []
    assert _warnings(caplog) == []
    msgs = [r.getMessage() for r in caplog.records]
    assert "  metadata: heuristics" in msgs and "  metadata: heuristics (offline)" in msgs


def test_crossref_fail_arxiv_ok_no_warning(monkeypatch, caplog):
    def handler(url, params):
        return FakeResp(200, text=_ARXIV_OK) if "arxiv" in url else FakeResp(404)
    _fake_http(monkeypatch, handler)
    text = "Learning grinding fast\ndoi:10.48550/arXiv.2301.12345\narXiv:2301.12345v2\n"
    with caplog.at_level(logging.INFO, logger="pdf2word"):
        meta = M.resolve_metadata(_blank_doc(), text, online=True)
    assert meta.source == "arxiv" and meta.first_author == "Lovelace"
    assert _warnings(caplog) == []


# ----------------------------------------------------------------------------- #43 User-Agent

def test_user_agent_has_version(monkeypatch):
    calls = _fake_http(monkeypatch, _crossref({"10.1000/x": {"title": ["T"]}}))
    M.crossref_lookup("10.1000/x")
    ua = calls[0]["headers"]["User-Agent"]
    assert __version__ in ua and "Perfectree-1215/PDF2Word" in ua


# ----------------------------------------------------------------------------- #125 one HTTP session

def test_one_session_per_conversion(monkeypatch):
    def handler(url, params):
        if "arxiv" in url:
            return FakeResp(503)
        return _crossref(_RECORDS)(url, params)
    calls = _fake_http(monkeypatch, handler)
    text = ("Some other title\ndoi:10.1000/missing.1\nhttps://doi.org/10.5281/zenodo.123456\n"
            "arXiv:2301.12345\n")
    M.resolve_metadata(_blank_doc(), text, online=True)
    assert len(calls) == 3                              # CrossRef x2, arXiv x1
    assert len({c["session"] for c in calls}) == 1      # ... over one requests.Session
