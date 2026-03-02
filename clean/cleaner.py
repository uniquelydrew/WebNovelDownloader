import re

class CleanerConfig:
    def __init__(self, aside_mode: str = "balanced", remove_footnote_markers: bool = True):
        self.aside_mode = aside_mode
        self.remove_footnote_markers = remove_footnote_markers

class Cleaner:
    # Common inline footnote markers
    _FOOTNOTE_PATTERNS = [
        re.compile(r"\[(\d{1,4})\]"),     # [1]
        re.compile(r"\s*\^\s*\d{1,4}\b"), # ^1
        re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+"),        # superscripts
    ]

    # Balanced: remove bracketed segments that look like translator/meta notes
    _ASIDE_BRACKET_META = re.compile(
        r"\[(?:\s*(?:tl|t\/l|translator|translators?|note|notes?|author(?:'s)?\s*note)\b)[^\]]*\]",
        re.IGNORECASE,
    )
    # Aggressive: remove any [...] segment
    _ASIDE_BRACKET_ANY = re.compile(r"\[[^\]]+\]")

    # Normalize whitespace
    _RE_TRAIL_SP = re.compile(r"[ \t]+\n")
    _RE_MULTI_NL = re.compile(r"\n{3,}")

    def __init__(self, cfg: CleanerConfig | None = None):
        self.cfg = cfg or CleanerConfig()

    def clean(self, text: str) -> str:
        t = text.replace("\r\n", "\n").replace("\r", "\n")

        mode = (self.cfg.aside_mode or "balanced").lower()
        if mode == "balanced":
            t = self._ASIDE_BRACKET_META.sub("", t)
        elif mode == "aggressive":
            t = self._ASIDE_BRACKET_ANY.sub("", t)
        elif mode == "off":
            pass
        else:
            raise ValueError(f"Unknown aside_mode: {self.cfg.aside_mode!r}")

        if self.cfg.remove_footnote_markers:
            for p in self._FOOTNOTE_PATTERNS:
                t = p.sub("", t)

        t = self._RE_TRAIL_SP.sub("\n", t)
        t = self._RE_MULTI_NL.sub("\n\n", t)
        return t.strip()
