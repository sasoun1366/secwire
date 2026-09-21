"""Where the news comes from: public security feeds, and the article behind a story.

Every source here is a feed a human can subscribe to for free. The tool asks each
one for its list, keeps what parses, and moves on: one dead feed in the morning
must not cost the channel its daily post, so failures are collected and reported
rather than raised.
"""

from __future__ import annotations

import gzip
import io
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import USER_AGENT
from . import text as T


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    url: str
    weight: int = 10
    about: str = ""
    html: str = ""


#: The desk. Weights are editorial: an advisory you can act on beats a vendor's
#: product launch, and a story broken by a newsroom beats a press release.
SOURCES: Tuple[Source, ...] = (
    Source("cisakev", "CISA — known exploited vulnerabilities",
           "https://www.cisa.gov/cybersecurity-advisories/all.xml", 13,
           "the vulnerabilities that are being exploited right now",
           "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"),
    Source("krebs", "Krebs on Security", "https://krebsonsecurity.com/feed/", 12,
           "investigative reporting, breaking the story is the norm",
           "https://krebsonsecurity.com/"),
    Source("thn", "The Hacker News", "https://feeds.feedburner.com/TheHackersNews", 11,
           "fast, broad coverage of attacks and patches", "https://thehackernews.com/"),
    Source("bleeping", "BleepingComputer", "https://www.bleepingcomputer.com/feed/", 11,
           "practitioner-focused, good on ransomware", "https://www.bleepingcomputer.com/"),
    Source("record", "The Record", "https://therecord.media/feed", 10,
           "policy and state-linked intrusion reporting", "https://therecord.media/"),
    Source("secweek", "SecurityWeek", "https://www.securityweek.com/feed/", 9,
           "industry reporting, good on enterprise vulns", "https://www.securityweek.com/"),
    Source("darkread", "Dark Reading", "https://www.darkreading.com/rss.xml", 9,
           "defender-side analysis", "https://www.darkreading.com/"),
    Source("sansisc", "SANS ISC — daily diary", "https://isc.sans.edu/rssfeed.xml", 8,
           "what handlers are seeing in the wild today", "https://isc.sans.edu/"),
)

BY_KEY: Dict[str, Source] = {s.key: s for s in SOURCES}


@dataclass
class Entry:
    """One item from a feed, cleaned up but not yet judged."""

    title: str
    link: str
    summary: str = ""
    published: Optional[datetime] = None
    source: Optional[Source] = None
    image: str = ""
    guid: str = ""
    score: float = 0.0
    why: str = ""

    @property
    def key(self) -> str:
        return self.guid or self.link or self.title

    @property
    def host(self) -> str:
        m = re.match(r"https?://([^/]+)", self.link or "")
        return m.group(1).replace("www.", "") if m else ""


class FeedError(RuntimeError):
    """A source could not be read. Never fatal — reported and skipped."""


def fetch(url: str, timeout: int = 25, opener=None) -> bytes:
    """GET a URL the way a careful script does: identified, bounded, decompressed."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.5",
            "Accept-Encoding": "gzip",
        },
    )
    call = opener or urllib.request.urlopen
    try:
        with call(request, timeout=timeout) as response:
            body = response.read()
            encoding = (response.headers.get("Content-Encoding") or "").lower()
    except urllib.error.HTTPError as exc:
        raise FeedError("HTTP %s from %s" % (exc.code, url)) from None
    except Exception as exc:                                  # noqa: BLE001 — any failure
        raise FeedError("%s: %s" % (type(exc).__name__, exc)) from None
    if "gzip" in encoding or body[:2] == b"\x1f\x8b":
        try:
            body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
        except OSError:
            pass
    return body


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, *names: str) -> str:
    for child in node:
        if _local(child.tag) in names:
            if child.text and child.text.strip():
                return child.text
            # An Atom link carries its URL in the href attribute.
            if child.get("href"):
                return child.get("href")
            if list(child):                                  # xhtml content
                return " ".join(child.itertext())
    return ""


def _as_datetime(raw: str) -> Optional[datetime]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        stamp = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        stamp = None
    if stamp is None:
        cleaned = raw.replace("Z", "+00:00")
        for cutter in (lambda s: s, lambda s: s[:19], lambda s: s[:10]):
            try:
                stamp = datetime.fromisoformat(cutter(cleaned))
                break
            except ValueError:
                continue
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def parse_feed(data: bytes, source: Optional[Source] = None) -> List[Entry]:
    """RSS 2.0, RSS 1.0/RDF and Atom all reduce to the same list of entries."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FeedError("not XML: %s" % exc) from None
    items = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    out: List[Entry] = []
    for node in items:
        title = T.tidy(_child_text(node, "title"))
        link = ""
        for child in node:
            tag = _local(child.tag)
            if tag == "link":
                link = (child.get("href") or child.text or "").strip() or link
                rel = (child.get("rel") or "alternate").lower()
                if rel == "alternate" and (child.get("href") or child.text):
                    break
        if not title or not link:
            continue
        summary = _child_text(node, "description", "summary", "content", "encoded")
        image = ""
        for child in node:
            tag = _local(child.tag)
            if tag == "enclosure" and "image" in (child.get("type") or ""):
                image = child.get("url") or ""
            elif tag in ("content", "thumbnail") and (child.get("type") or "").startswith("image"):
                image = child.get("url") or image
            elif tag == "thumbnail":
                image = child.get("url") or image
        out.append(
            Entry(
                title=title,
                link=link.strip(),
                summary=T.tidy(summary),
                published=_as_datetime(
                    _child_text(node, "pubdate", "published", "updated", "date")
                ),
                source=source,
                image=image,
                guid=_child_text(node, "guid", "id") or link,
            )
        )
    return out


def collect(
    sources: Sequence[Source] = SOURCES,
    timeout: int = 25,
    opener=None,
) -> Tuple[List[Entry], List[str]]:
    """Read every feed. Returns (entries, complaints) — complaints are for the log."""
    entries: List[Entry] = []
    errors: List[str] = []
    for source in sources:
        try:
            rows = parse_feed(fetch(source.url, timeout=timeout, opener=opener), source)
        except FeedError as exc:
            errors.append("%s: %s" % (source.key, exc))
            continue
        if not rows:
            errors.append("%s: parsed, but no items" % source.key)
        entries.extend(rows)
    return entries, errors


# --------------------------------------------------------------------------- article


_META = re.compile(r"<meta\s+([^>]+?)/?>", re.IGNORECASE | re.DOTALL)
_ATTR = re.compile(r"([\w:.-]+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'>]+)")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_IMG_SRC = re.compile(r"""<img[^>]+src\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def article_meta(page: bytes) -> Dict[str, str]:
    """Open Graph (and the usual fallbacks) out of an article page."""
    head = page[:400_000].decode("utf-8", "replace")
    found: Dict[str, str] = {}
    for blob in _META.findall(head):
        attrs = {k.lower(): v.strip("\"'") for k, v in _ATTR.findall(blob)}
        name = (attrs.get("property") or attrs.get("name") or "").lower()
        content = attrs.get("content") or ""
        if name and content and name not in found:
            found[name] = content
    if "og:image" not in found and "twitter:image" in found:
        found["og:image"] = found["twitter:image"]
    if "og:title" not in found:
        match = _TITLE.search(head)
        if match:
            found["og:title"] = T.strip_html(match.group(1))
    if "og:description" not in found and "description" in found:
        found["og:description"] = found["description"]
    return found


def enrich(entry: Entry, timeout: int = 25, opener=None) -> Entry:
    """Fetch the story's own page for its photograph and a fuller opening line.

    One request, for the story of the day only. If it fails, the entry keeps what
    the feed gave it — a post without a photograph is still a post.
    """
    if not entry.link:
        return entry
    try:
        page = fetch(entry.link, timeout=timeout, opener=opener)
    except FeedError:
        return entry
    meta = article_meta(page)
    image = meta.get("og:image", "").strip()
    if image.startswith("//"):
        image = "https:" + image
    if image.startswith("http"):
        entry.image = image
    description = T.tidy(meta.get("og:description", ""))
    if len(description) > len(entry.summary):
        entry.summary = description
    headline = T.strip_html(meta.get("og:title", ""))
    # A shortened feed title is a real nuisance: use the page's own headline when it
    # says more, which is usually the case for a title the feed cut to fit.
    if headline and len(headline) > len(entry.title) and entry.title.endswith(("…", "...")):
        entry.title = headline
    return entry


def hours_ago(entry: Entry, now: Optional[datetime] = None) -> Optional[float]:
    if not entry.published:
        return None
    now = now or datetime.now(timezone.utc)
    delta = now - entry.published
    return max(0.0, delta.total_seconds() / 3600.0)


def is_fresh(entry: Entry, now: Optional[datetime] = None, limit_hours: float = 96.0) -> bool:
    age = hours_ago(entry, now)
    return age is None or age <= limit_hours


def within(entries: Iterable[Entry], now: Optional[datetime] = None,
           days: int = 1) -> List[Entry]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return [e for e in entries if not e.published or e.published >= cutoff]
