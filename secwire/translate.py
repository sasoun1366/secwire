"""English headlines into Persian, with a cache, a chain, and a graceful way to fail.

The channel's audience reads Persian first, so a headline left in English is a
headline half the readers scroll past. There is no API key in this project and
there will not be one: the tool asks free endpoints in turn, keeps every
translation it has ever seen on disk, and when they are all having a bad morning
the post goes out in English with a Persian label rather than not going out at all.

The endpoints are unofficial. They are also cheap to avoid: point
`SECWIRE_TRANSLATE_URL` at your own service (any URL with `{q}` in it, answering
either text or JSON), or switch translation off with `SECWIRE_TRANSLATE=0` and the
Persian half of the post becomes a Persian frame around the original headline.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import urllib.parse
from typing import Callable, Dict, List, Optional, Tuple

from . import text as T

CUSTOM_ENV = "SECWIRE_TRANSLATE_URL"


def _enc(text: str) -> str:
    return urllib.parse.quote(text)


def _nested(payload) -> str:
    """[[["translated", "source", …], …]] — the shape of the gtx frontend."""
    pieces = []
    for chunk in payload[0]:
        if isinstance(chunk, list) and chunk and isinstance(chunk[0], str):
            pieces.append(chunk[0])
    return "".join(pieces).strip()


def _flat(payload) -> str:
    """["translated"] or {"sentences": [{"trans": "…"}]} — the dict-chrome-ex shapes."""
    if isinstance(payload, dict):
        rows = payload.get("sentences") or []
        return "".join(row.get("trans", "") for row in rows if isinstance(row, dict)).strip()
    if isinstance(payload, list):
        if payload and isinstance(payload[0], list):
            return _nested(payload)
        return "".join(str(piece) for piece in payload if isinstance(piece, str)).strip()
    return ""


def _plain(payload) -> str:
    if isinstance(payload, str):
        return payload.strip()
    return ""


#: (name, url template, parser). Tried in order; the first real translation wins.
PROVIDERS: Tuple[Tuple[str, str, Callable], ...] = (
    ("google-clients5",
     "https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=en&tl=fa&q={q}",
     _flat),
    ("google-gtx",
     "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=fa&dt=t&q={q}",
     _nested),
    ("google-gtx-alt",
     "https://translate.googleapis.com/translate_a/single?client=gtx&dj=1&sl=en&tl=fa&dt=t&q={q}",
     _flat),
)


class Translator:
    def __init__(self, cache: Optional[pathlib.Path] = None, transport=None,
                 enabled: bool = True, providers=None):
        self.enabled = enabled and os.environ.get("SECWIRE_TRANSLATE", "1").lower() not in (
            "0", "no", "off", "false")
        self.transport = transport            # callable(url) -> bytes, injectable for tests
        self.cache_path = cache
        self.cache: Dict[str, str] = {}
        self.calls: Dict[str, int] = {}
        self.failures = 0
        self.custom = os.environ.get(CUSTOM_ENV, "").strip()
        self.providers = list(providers or PROVIDERS)
        if self.custom:
            self.providers.insert(0, ("custom", self.custom, _first_that_parses))
        if cache and cache.exists():
            try:
                self.cache = json.loads(cache.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                self.cache = {}

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]

    def _default_transport(self, url: str) -> bytes:
        from .sources import fetch

        return fetch(url, timeout=20)

    def _ask(self, name: str, url: str, parse: Callable) -> Optional[str]:
        self.calls[name] = self.calls.get(name, 0) + 1
        try:
            raw = (self.transport or self._default_transport)(url)
        except Exception:                                     # noqa: BLE001 — never fatal
            return None
        if hasattr(raw, "read"):                              # a response object (see fixtures)
            raw = raw.read()
        body = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        try:
            payload = json.loads(body)
        except ValueError:
            return parse(body) if parse is _first_that_parses else None
        try:
            return parse(payload) or None
        except (TypeError, IndexError, KeyError, AttributeError):
            return None

    # ------------------------------------------------------------------ public
    def to_persian(self, text: str) -> Optional[str]:
        """Persian text, or None when it cannot be had. Callers must handle None."""
        text = (text or "").strip()
        if not text or not self.enabled:
            return None
        key = self._key(text)
        if key in self.cache:
            return self.cache[key]
        for name, template, parse in self.providers:
            url = template.replace("{q}", _enc(text))
            out = self._ask(name, url, parse)
            if out and not _looks_untranslated(text, out):
                self.cache[key] = T.truncate(out, 900)
                return self.cache[key]
        self.failures += 1
        return None

    def save(self) -> Optional[pathlib.Path]:
        if not self.cache_path:
            return None
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
        return self.cache_path

    def stats(self) -> str:
        tried = ", ".join("%s×%d" % (k, v) for k, v in sorted(self.calls.items())) or "none"
        return "translator: %d cached, %d misses, %s — %s" % (
            len(self.cache), self.failures, "on" if self.enabled else "off", tried)


def _first_that_parses(payload) -> str:
    if isinstance(payload, dict):
        # LibreTranslate and friends answer {"translatedText": "…"}.
        for key in ("translatedText", "translation", "text", "result"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for parser in (_plain, _flat, _nested):
        try:
            out = parser(payload)
        except (TypeError, IndexError, KeyError):
            continue
        if out:
            return out
    return ""


_LATIN = re.compile(r"[A-Za-z]{3,}")
_PERSIAN = re.compile(r"[\u0600-\u06FF]")


def _looks_untranslated(source: str, result: str) -> bool:
    """True when the 'translation' is the English sentence handed back unchanged."""
    if _PERSIAN.search(result):
        return False
    words_in = len(_LATIN.findall(source))
    words_out = len(_LATIN.findall(result))
    return words_in >= 4 and words_out >= max(3, int(words_in * 0.8))


def persian_or_none(translator: Optional[Translator], text: str) -> Optional[str]:
    if translator is None:
        return None
    out = translator.to_persian(text)
    return clean_persian(out) if out else None


def translated(translator: Optional[Translator], text: str, fallback: str = "") -> str:
    """Persian if we have it, otherwise the fallback the caller chose."""
    return persian_or_none(translator, text) or fallback


def clean_persian(text: str) -> str:
    """Unofficial endpoints produce spacing artefacts; keep the line printable."""
    text = re.sub(r"[ \t]+", " ", (text or "").replace("\u200c ", "\u200c")).strip()
    return T.truncate(text, 900)
