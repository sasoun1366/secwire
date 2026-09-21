"""Turning feed markup into something a person would read.

Feeds are dirty: CDATA, entities, "&nbsp;", adverts stapled to the end of a
summary, whitespace that came from a CMS. Everything that touches text goes
through here so the rendering code can stay boring.
"""

from __future__ import annotations

import html
import re

_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# Feed summaries very often end with a call to action that is not part of the story.
_TAIL = re.compile(
    r"(the post .{0,120}? appeared first on .{0,80}\.?$)"
    r"|((read|continue reading|read more|source|via)\s*[:\-–>]?\s*.{0,60}$)"
    r"|(\[?(sponsored|advertisement|advert)\b.*$)",
    re.IGNORECASE | re.DOTALL,
)


def strip_html(raw: str) -> str:
    """Plain text out of a feed field: tags gone, entities decoded, spaces tidy."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = _TAGS.sub(" ", text)
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    return _WS.sub(" ", text).strip()


def tidy(raw: str) -> str:
    """Plain text with the boilerplate at the end removed."""
    text = strip_html(raw)
    text = _TAIL.sub("", text).strip()
    while text.endswith((" .", " ,", "-", "–", "|")):
        text = text[:-1].strip()
    return text


def truncate(text: str, limit: int, ellipsis: str = "…") -> str:
    """Cut on a word boundary, never mid-word, never longer than the limit.

    Newlines are structure — a post is a headline, a paragraph and a link — so this
    keeps them and only collapses runs of spaces and tabs.
    """
    text = re.sub(r"[ \t]+", " ", (text or "").replace("\r\n", "\n")).strip()
    if len(text) <= limit:
        return text
    room = max(1, limit - len(ellipsis))
    cut = text[:room]
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    if boundary > room * 0.6:
        cut = cut[:boundary]
    return cut.rstrip(" ,;:-–\n") + ellipsis


def sentence_trim(text: str, sentences: int = 2, limit: int = 420) -> str:
    """The opening sentence or two — enough to say what happened, no more."""
    text = _WS.sub(" ", (text or "").strip())
    if not text:
        return ""
    # Split after . ! ? when the next character looks like a new sentence, and not
    # inside an abbreviation such as "CVE-2026-1234." followed by more numbers.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", text)
    out = " ".join(parts[:sentences]).strip()
    if len(out) < 40 and len(parts) > sentences:
        out = " ".join(parts[: sentences + 1]).strip()
    return truncate(out, limit)


def esc(text: str) -> str:
    """Escape for Telegram's HTML parse mode. Everything dynamic goes through it."""
    return html.escape(text or "", quote=False)


def esc_attr(text: str) -> str:
    return html.escape(text or "", quote=True)


def link(url: str, label: str) -> str:
    return '<a href="%s">%s</a>' % (esc_attr(url), esc(label))


def bullets(items) -> str:
    """A Telegram-friendly bullet list: no markdown, a real character."""
    return "\n".join("• %s" % esc(item) for item in items if item)


def fa_digits(text: str) -> str:
    """Latin digits to Persian ones, for the Persian half of a post."""
    table = {ord("0") + i: chr(0x06F0 + i) for i in range(10)}
    return (text or "").translate(table)
