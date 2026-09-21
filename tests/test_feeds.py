"""Reading the wire: every source parses, and the dirt in the fields is cleaned."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from secwire import fixtures as FX
from secwire import text as T

from secwire import sources as SD


def test_every_bundled_feed_parses(wire):
    desks = {entry.source.key for entry in wire if entry.source}
    assert len(desks) >= 6, "the bundle should carry most of the desk"
    for entry in wire:
        assert entry.title and entry.link.startswith("http")
        assert entry.source is not None
        assert entry.key


def test_a_feed_is_not_the_place_for_html():
    dirty = ("<p>Texas <b>sues</b> a data broker &amp;nbsp; over&nbsp;records</p>"
             "<p>The post <a href='x'>Bits About Money</a> appeared first on Krebs.</p>")
    clean = T.tidy(dirty)
    assert "<" not in clean
    assert "sues a data broker" in clean
    assert "appeared first on" not in clean, "the footer of a feed item is not the story"


def test_atom_and_rss_reduce_to_the_same_entry():
    rss = (b'<?xml version="1.0"?><rss version="2.0"><channel><item>'
           b"<title>T</title><link>https://example.com/a</link>"
           b"<description>D</description><pubDate>Mon, 21 Sep 2026 06:00:00 +0000</pubDate>"
           b"</item></channel></rss>")
    atom = (b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            b"<title>T</title><link rel=\"alternate\" href=\"https://example.com/a\"/>"
            b"<summary>D</summary><updated>2026-09-21T06:00:00Z</updated>"
            b"</entry></feed>")
    left, right = SD.parse_feed(rss), SD.parse_feed(atom)
    assert left[0].title == right[0].title == "T"
    assert left[0].link == right[0].link
    assert left[0].summary == right[0].summary == "D"
    assert abs((left[0].published - right[0].published).total_seconds()) < 1


def test_a_broken_feed_is_a_complaint_not_a_crash(monkeypatch):
    class Opener:
        def __call__(self, request, timeout=25):
            raise OSError("the network is asleep")

    entries, errors = SD.collect(SD.SOURCES[:3], opener=Opener())
    assert entries == []
    assert len(errors) == 3
    assert all("asleep" in row for row in errors)


def test_age_and_the_freshness_window():
    now = datetime(2026, 9, 21, 6, 30, tzinfo=timezone.utc)
    entry = SD.Entry("t", "https://example.com", published=now - timedelta(hours=5))
    assert round(SD.hours_ago(entry, now)) == 5
    assert SD.is_fresh(entry, now)
    stale = SD.Entry("t", "https://example.com", published=now - timedelta(hours=200))
    assert not SD.is_fresh(stale, now)
    assert SD.within([entry, stale], now=now, days=4) == [entry]
    undated = SD.Entry("t", "https://example.com")
    assert SD.is_fresh(undated, now)


def test_the_article_page_gives_up_its_metadata():
    page = (b'<html><head><meta property="og:title" content="A headline">'
            b'<meta name="description" content="The short version.">'
            b'<meta property="og:image" content="//cdn.example.com/pic.jpg"></head>'
            b"<body><p>text</p></body></html>")
    meta = SD.article_meta(page)
    assert meta["og:title"] == "A headline"
    assert meta["og:description"] == "The short version."
    assert meta["og:image"] == "//cdn.example.com/pic.jpg"


def test_an_article_without_a_picture_keeps_what_the_feed_gave():
    entries, _ = FX.entries()
    cisa = [e for e in entries if e.source.key == "cisakev"][0]
    before = cisa.summary
    assert cisa.image == ""
    SD.enrich(cisa, opener=FX.FixtureOpener())
    assert cisa.image == "", "this page has no og:image and we must not invent one"
    assert cisa.summary, "the summary still stands"
    assert len(cisa.summary) >= min(len(before), 40)


def test_an_article_with_a_photograph_gives_it_up():
    entry = SD.Entry("A story", "https://www.bleepingcomputer.com/news/x/", source=SD.BY_KEY["bleeping"])
    page = (b'<html><head><meta property="og:image" '
            b'content="https://www.bleepingcomputer.com/pic.jpg"></head><body></body></html>')

    class Opener:
        def __call__(self, request, timeout=25):
            return FX.FixtureResponse(page)

    SD.enrich(entry, opener=Opener())
    assert entry.image == "https://www.bleepingcomputer.com/pic.jpg"


def test_fixture_opener_answers_only_what_it_has(tmp_path):
    opener = FX.FixtureOpener()
    response = opener("https://www.cisa.gov/cybersecurity-advisories/all.xml")
    assert b"<rss" in response.read() or b"<feed" in response.read()
    with pytest.raises(OSError):
        FX.FixtureOpener(root=tmp_path)("https://example.com/nowhere")


def test_the_description_lists_what_is_bundled():
    text = FX.describe()
    assert "offline fixtures" in text
    assert "cisakev" in text
