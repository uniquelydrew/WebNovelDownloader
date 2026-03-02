from __future__ import annotations
from typing import Optional, Protocol, runtime_checkable, Any

FOOTNOTE_BLOCK_XPATH = ".//*[starts-with(@id,'footnote-')]"
FOOTNOTE_REF_LINK_XPATH = ".//a[starts-with(@href,'#footnote-ref-')]"

@runtime_checkable
class ResponseLike(Protocol):
    def xpath(self, query: str): ...

def _string_value(x: Any) -> str:
    # scrapy SelectorList supports .get()
    get = getattr(x, "get", None)
    if callable(get):
        return get() or ""
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        if not x:
            return ""
        v = x[0]
        if isinstance(v, str):
            return v
        tc = getattr(v, "text_content", None)
        if callable(tc):
            return tc() or ""
        return str(v)
    tc = getattr(x, "text_content", None)
    if callable(tc):
        return tc() or ""
    return str(x)

def _node_text_len(node: Any) -> int:
    try:
        v = node.xpath("string(.)")
        return len(_string_value(v))
    except Exception:
        tc = getattr(node, "text_content", None)
        if callable(tc):
            return len(tc() or "")
        return len(str(node))

def find_content_container(response: ResponseLike) -> Optional[Any]:
    nodes = response.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' chapter-content ')]")
    if nodes:
        return nodes[0]

    nodes = response.xpath("//div[.//a[starts-with(@href,'#footnote-ref-')]]")
    if nodes:
        return nodes[0]

    divs = response.xpath("//div[count(.//p) > 5]")
    if divs:
        return max(divs, key=_node_text_len)

    nodes = response.xpath("//main|//article")
    if nodes:
        return nodes[0]
    return None

def strip_footnotes_inplace(container: Any) -> None:
    for node in container.xpath(FOOTNOTE_BLOCK_XPATH):
        target = getattr(node, "root", node)
        parent = getattr(target, "getparent", lambda: None)()
        if parent is not None:
            parent.remove(target)

    for node in container.xpath(FOOTNOTE_REF_LINK_XPATH):
        target = getattr(node, "root", node)
        parent = getattr(target, "getparent", lambda: None)()
        if parent is not None:
            parent.remove(target)

def extract_text(container: Any) -> str:
    strip_footnotes_inplace(container)

    blocks = container.xpath(".//h1|.//h2|.//h3|.//h4|.//p|.//li|.//blockquote|.//pre")
    parts: list[str] = []
    for b in blocks:
        try:
            txt = _string_value(b.xpath("string(.)")).strip()
        except Exception:
            tc = getattr(b, "text_content", None)
            txt = (tc() if callable(tc) else str(b)).strip()

        if txt:
            parts.append(" ".join(txt.split()))
    return "\n".join(parts).strip()
