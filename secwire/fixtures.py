"""Bundled pages, so the tool can be run — and tested — with no network at all.

`--offline` is not a mock: the same code path runs, but every HTTP call is answered
from `secwire/fixtures/`. That is what makes it possible to show a reader exactly
what tomorrow's post will look like, and to let CI prove the whole pipeline without
touching anybody's newsroom.
"""

from __future__ import annotations

import json
import pathlib
import urllib.parse
from typing import Dict, Optional

from . import story as S
from .sources import SOURCES, parse_payload

ROOT = pathlib.Path(__file__).parent / "fixtures"
TRANSLATE_FIXTURE = ROOT / "translate.json"
KEV_FIXTURE = ROOT / "cisakev-kev.json"
ARTICLE_FIXTURE = ROOT / "article.html"
TITLE_FA = "«پیش‌نمایش آفلاین»"


class FixtureResponse:
    """Enough of an http.client response for our callers: read(), headers, context."""

    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status
        self.headers: Dict[str, str] = {"Content-Encoding": "", "Content-Type": "text/xml"}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FixtureResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class FixtureOpener:
    """Serves the bundled pages for any URL the tool asks for."""

    def __init__(self, root: Optional[pathlib.Path] = None, quiet: bool = True):
        self.root = pathlib.Path(root or ROOT)
        self.quiet = quiet
        self.served: list = []
        self.translations = self._load_translations()

    @staticmethod
    def _load_translations() -> Dict[str, str]:
        if TRANSLATE_FIXTURE.exists():
            try:
                return json.loads(TRANSLATE_FIXTURE.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return {}
        return {}

    def path_for(self, url: str) -> Optional[pathlib.Path]:
        if "translate" in url:
            return TRANSLATE_FIXTURE
        if "kev-data" in url and KEV_FIXTURE.exists():
            return KEV_FIXTURE
        for source in SOURCES:
            if url.startswith(source.url) or url.rstrip("/") == source.url.rstrip("/"):
                candidate = self.root / ("%s.xml" % source.key)
                if candidate.exists():
                    return candidate
        article = self.root / "article.html"
        if article.exists():
            return article
        return None

    def __call__(self, request, timeout: int = 25):
        url = getattr(request, "full_url", str(request))
        self.served.append(url)
        if "translate" in url:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q", [""])[0]
            persian = self.translations.get(query)
            if not persian:
                # Answer with the English text unchanged: the translator must refuse
                # to call that a translation, which is the behaviour we want tested.
                persian = query
            return FixtureResponse(
                json.dumps([[["%s" % persian, query, None, None, 1]]]).encode("utf-8")
            )
        path = self.path_for(url)
        if path is None:
            raise OSError("offline: no fixture for %s" % url)
        return FixtureResponse(path.read_bytes())


def entries(root: Optional[pathlib.Path] = None):
    """The fixtures, read exactly like live feeds, with their sources attached."""
    root = pathlib.Path(root or ROOT)
    out: list = []
    errors: list = []
    for source in SOURCES:
        path = root / ("%s.xml" % source.key)
        if not path.exists():
            continue
        try:
            out.extend(parse_payload(path.read_bytes(), source))
        except Exception as exc:                              # noqa: BLE001 — fixture, reported
            errors.append("%s: %s" % (source.key, exc))
    return out, errors


def describe() -> str:
    rows = ["offline fixtures in %s" % ROOT]
    for source in SOURCES:
        path = ROOT / ("%s.xml" % source.key)
        if path.exists():
            count = len(parse_payload(path.read_bytes(), source))
            rows.append("  %-9s %2d items  %s" % (source.key, count, source.name))
        if KEV_FIXTURE.exists() and source.key == "cisakev":
            rows.append("  %-9s %2d items  the KEV catalog itself (the fallback address)"
                        % ("kev-json", len(parse_payload(KEV_FIXTURE.read_bytes(), source))))
    if TRANSLATE_FIXTURE.exists():
        rows.append("  translations: %d cached pairs"
                    % len(json.loads(TRANSLATE_FIXTURE.read_text(encoding="utf-8"))))
    return "\n".join(rows)
