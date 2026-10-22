"""Recover characters that PDF text extraction returns as Private-Use-Area code points.

Word/MathType documents typeset Greek letters and operators with the legacy *Symbol*
font. Such glyphs usually come out of the text layer as U+F0xx (the low byte being the
original Symbol-font code), which Markdown viewers render as nothing. We map them back
through the Adobe Symbol encoding.
"""
from __future__ import annotations

import re

_SYMBOL_ENCODING: dict[int, str] = {
    0x20: " ", 0x21: "!", 0x22: "\u2200", 0x23: "#", 0x24: "\u2203", 0x25: "%", 0x26: "&",
    0x27: "\u220d", 0x28: "(", 0x29: ")", 0x2A: "\u2217", 0x2B: "+", 0x2C: ",", 0x2D: "\u2212",
    0x2E: ".", 0x2F: "/",
    0x3A: ":", 0x3B: ";", 0x3C: "<", 0x3D: "=", 0x3E: ">", 0x3F: "?", 0x40: "\u2245",
    0x41: "\u0391", 0x42: "\u0392", 0x43: "\u03a7", 0x44: "\u0394", 0x45: "\u0395", 0x46: "\u03a6",
    0x47: "\u0393", 0x48: "\u0397", 0x49: "\u0399", 0x4A: "\u03d1", 0x4B: "\u039a", 0x4C: "\u039b",
    0x4D: "\u039c", 0x4E: "\u039d", 0x4F: "\u039f", 0x50: "\u03a0", 0x51: "\u0398", 0x52: "\u03a1",
    0x53: "\u03a3", 0x54: "\u03a4", 0x55: "\u03a5", 0x56: "\u03c2", 0x57: "\u03a9", 0x58: "\u039e",
    0x59: "\u03a8", 0x5A: "\u0396", 0x5B: "[", 0x5C: "\u2234", 0x5D: "]", 0x5E: "\u22a5", 0x5F: "_",
    0x60: "\u203e",
    0x61: "\u03b1", 0x62: "\u03b2", 0x63: "\u03c7", 0x64: "\u03b4", 0x65: "\u03b5", 0x66: "\u03c6",
    0x67: "\u03b3", 0x68: "\u03b7", 0x69: "\u03b9", 0x6A: "\u03d5", 0x6B: "\u03ba", 0x6C: "\u03bb",
    0x6D: "\u03bc", 0x6E: "\u03bd", 0x6F: "\u03bf", 0x70: "\u03c0", 0x71: "\u03b8", 0x72: "\u03c1",
    0x73: "\u03c3", 0x74: "\u03c4", 0x75: "\u03c5", 0x76: "\u03d6", 0x77: "\u03c9", 0x78: "\u03be",
    0x79: "\u03c8", 0x7A: "\u03b6", 0x7B: "{", 0x7C: "|", 0x7D: "}", 0x7E: "\u223c",
    0xA0: "\u20ac", 0xA1: "\u03d2", 0xA2: "\u2032", 0xA3: "\u2264", 0xA4: "\u2044", 0xA5: "\u221e",
    0xA6: "\u0192", 0xA7: "\u2663", 0xA8: "\u2666", 0xA9: "\u2665", 0xAA: "\u2660", 0xAB: "\u2194",
    0xAC: "\u2190", 0xAD: "\u2191", 0xAE: "\u2192", 0xAF: "\u2193", 0xB0: "\u00b0", 0xB1: "\u00b1",
    0xB2: "\u2033", 0xB3: "\u2265", 0xB4: "\u00d7", 0xB5: "\u221d", 0xB6: "\u2202", 0xB7: "\u2022",
    0xB8: "\u00f7", 0xB9: "\u2260", 0xBA: "\u2261", 0xBB: "\u2248", 0xBC: "\u2026", 0xBD: "\u23d0",
    0xBE: "\u23af", 0xBF: "\u21b5", 0xC0: "\u2135", 0xC1: "\u2111", 0xC2: "\u211c", 0xC3: "\u2118",
    0xC4: "\u2297", 0xC5: "\u2295", 0xC6: "\u2205", 0xC7: "\u2229", 0xC8: "\u222a", 0xC9: "\u2283",
    0xCA: "\u2287", 0xCB: "\u2284", 0xCC: "\u2282", 0xCD: "\u2286", 0xCE: "\u2208", 0xCF: "\u2209",
    0xD0: "\u2220", 0xD1: "\u2207", 0xD2: "\u00ae", 0xD3: "\u00a9", 0xD4: "\u2122", 0xD5: "\u220f",
    0xD6: "\u221a", 0xD7: "\u22c5", 0xD8: "\u00ac", 0xD9: "\u2227", 0xDA: "\u2228", 0xDB: "\u21d4",
    0xDC: "\u21d0", 0xDD: "\u21d1", 0xDE: "\u21d2", 0xDF: "\u21d3", 0xE0: "\u25ca", 0xE1: "\u2329",
    0xE2: "\u00ae", 0xE3: "\u00a9", 0xE4: "\u2122", 0xE5: "\u2211", 0xE6: "\u239b", 0xE7: "\u239c",
    0xE8: "\u239d", 0xE9: "\u23a1", 0xEA: "\u23a2", 0xEB: "\u23a3", 0xEC: "\u23a7", 0xED: "\u23a8",
    0xEE: "\u23a9", 0xEF: "\u23aa", 0xF1: "\u232a", 0xF2: "\u222b", 0xF3: "\u2320", 0xF4: "\u23ae",
    0xF5: "\u2321", 0xF6: "\u239e", 0xF7: "\u239f", 0xF8: "\u23a0", 0xF9: "\u23a4", 0xFA: "\u23a5",
    0xFB: "\u23a6", 0xFC: "\u23ab", 0xFD: "\u23ac", 0xFE: "\u23ad",
}
for _d in range(10):
    _SYMBOL_ENCODING[0x30 + _d] = str(_d)

_PUA_RE = re.compile("[\ue000-\uf8ff]")

# PUA code points that are *not* Symbol-font bytes are dropped (they are invisible anyway).
def _replace(m: re.Match) -> str:
    code = ord(m.group(0))
    if 0xF000 <= code <= 0xF0FF:
        return _SYMBOL_ENCODING.get(code & 0xFF, "")
    return ""


def map_pua(text: str) -> str:
    """Replace U+F0xx (Symbol-font) code points by their Unicode equivalents; drop other PUA chars."""
    if not text:
        return text
    return _PUA_RE.sub(_replace, text)


def has_pua(text: str) -> bool:
    return bool(_PUA_RE.search(text or ""))


# A few Unicode characters that MathJax/LaTeX would rather see as commands
# (inlinemath.char_to_latex and the hint letters of mathocr use it).
UNICODE_TO_LATEX: dict[str, str] = {
    "\u2202": r"\partial ", "\u2207": r"\nabla ", "\u2211": r"\sum ", "\u220f": r"\prod ",
    "\u222b": r"\int ", "\u221e": r"\infty ", "\u2264": r"\le ", "\u2265": r"\ge ", "\u2260": r"\ne ",
    "\u2248": r"\approx ", "\u2261": r"\equiv ", "\u221d": r"\propto ", "\u00b1": r"\pm ",
    "\u00d7": r"\times ", "\u22c5": r"\cdot ", "\u2212": "-", "\u2192": r"\to ", "\u2208": r"\in ",
    "\u2297": r"\otimes ", "\u2295": r"\oplus ", "\u221a": r"\sqrt ", "\u00b0": r"^\circ ",
    "\u03b1": r"\alpha ", "\u03b2": r"\beta ", "\u03b3": r"\gamma ", "\u03b4": r"\delta ",
    "\u03b5": r"\varepsilon ", "\u03b6": r"\zeta ", "\u03b7": r"\eta ", "\u03b8": r"\theta ",
    "\u03b9": r"\iota ", "\u03ba": r"\kappa ", "\u03bb": r"\lambda ", "\u03bc": r"\mu ",
    "\u03bd": r"\nu ", "\u03be": r"\xi ", "\u03c0": r"\pi ", "\u03c1": r"\rho ", "\u03c3": r"\sigma ",
    "\u03c4": r"\tau ", "\u03c5": r"\upsilon ", "\u03c6": r"\varphi ", "\u03d5": r"\phi ",
    "\u03c7": r"\chi ", "\u03c8": r"\psi ", "\u03c9": r"\omega ", "\u0393": r"\Gamma ",
    "\u0394": r"\Delta ", "\u0398": r"\Theta ", "\u039b": r"\Lambda ", "\u039e": r"\Xi ",
    "\u03a0": r"\Pi ", "\u03a3": r"\Sigma ", "\u03a5": r"\Upsilon ", "\u03a6": r"\Phi ",
    "\u03a8": r"\Psi ", "\u03a9": r"\Omega ",
    # variants and extra relations/operators (used by inlinemath for text-layer formulas)
    "\u03d1": r"\vartheta ", "\u03d6": r"\varpi ", "\u03f1": r"\varrho ", "\u03c2": r"\varsigma ",
    "\u03f5": r"\epsilon ", "\u00b5": r"\mu ", "\u2113": r"\ell ", "\u0127": r"\hbar ",
    "\u22a5": r"\perp ", "\u2225": r"\parallel ", "\u223c": r"\sim ", "\u2243": r"\simeq ",
    "\u2213": r"\mp ", "\u226a": r"\ll ", "\u226b": r"\gg ", "\u2190": r"\leftarrow ",
    "\u2194": r"\leftrightarrow ", "\u21d2": r"\Rightarrow ", "\u21d4": r"\Leftrightarrow ",
    "\u2209": r"\notin ", "\u2282": r"\subset ", "\u2283": r"\supset ", "\u2286": r"\subseteq ",
    "\u2287": r"\supseteq ", "\u222a": r"\cup ", "\u2229": r"\cap ", "\u2227": r"\wedge ",
    "\u2228": r"\vee ", "\u2218": r"\circ ", "\u2217": r"\ast ", "\u2219": r"\cdot ",
    "\u00b7": r"\cdot ", "\u2223": r"\mid ", "\u2200": r"\forall ", "\u2203": r"\exists ",
    "\u2205": r"\emptyset ", "\u2026": r"\ldots ", "\u22ef": r"\cdots ", "\u2032": "'", "\u2033": "''",
}
