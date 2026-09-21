"""The post itself: length limits, escaping, both languages, and the fallbacks."""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

from _helpers import assert_private, plain

from conftest import FROZEN

from secwire import fixtures as FXMOD
from secwire import render, state as ST, story as S, text as T, translate as TR

NOW = datetime(2026, 9, 21, 6, 30, tzinfo=timezone.utc)


def test_the_caption_fits_the_limit_telegram_sets(digest, translator):
    post = render.build(digest, translator=translator, when=NOW)
    caption = post.messages[0]
    assert caption.kind == "photo"
    assert len(caption.text) <= render.CAPTION_LIMIT
    assert "<b>" in caption.text and "@luyavaai" in caption.text


def test_a_caption_that_would_be_too_long_loses_the_lead_not_the_headline(wire, translator):
    digest = S.build(wire, now=NOW, also=0)
    digest.story.title = "A very long headline " * 12
    digest.story.summary = "And a very long summary. " * 40
    post = render.build(digest, translator=translator, when=NOW)
    text = post.messages[0].text
    assert len(text) <= render.CAPTION_LIMIT
    assert "A very long headline" in plain(text)


def test_both_languages_are_present_and_apart(digest, translator):
    post = render.build(digest, translator=translator, when=NOW)
    labels = [message.label for message in post.messages]
    assert labels[:3] == ["caption", "fa", "en"]
    fa = plain([m for m in post.messages if m.label == "fa"][0].text)
    en = plain([m for m in post.messages if m.label == "en"][0].text)
    assert "چه کار کنیم" in fa and "What to do" in en
    assert "شهریور" in fa and "September" in en
    for message in post.messages:
        assert len(message.text) <= render.MESSAGE_LIMIT


def test_the_english_body_carries_the_original_headline(digest, translator):
    post = render.build(digest, translator=translator, when=NOW)
    en = [m for m in post.messages if m.label == "en"][0].text
    assert T.esc(digest.story.title) in en


def test_without_translation_the_persian_half_says_so(digest):
    post = render.build(digest, translator=None, when=NOW)
    fa = plain([m for m in post.messages if m.label == "fa"][0].text)
    assert "ترجمهٔ ماشینی در دسترس نبود" in fa
    assert digest.story.title in fa, "the original headline stands in"


def test_feed_text_can_never_break_the_markup(wire, translator):
    digest = S.build(wire, now=NOW, also=0)
    digest.story.title = 'Router <b>flaw</b> & "quotes" in <script>alert(1)</script>'
    post = render.build(digest, translator=translator, when=NOW)
    for message in post.messages:
        body = message.text
        assert "&lt;b&gt;flaw&lt;/b&gt;" in body, "feed text is escaped, never markup"
        assert "<script>" not in body and "&lt;script&gt;" in body
        assert "&amp;" in body
        assert body.count("<b>") == body.count("</b>"), "no tag is left open"
        assert body.count("<i>") == body.count("</i>")


def test_a_story_without_a_photograph_gets_the_bundled_cover(wire, translator):
    digest = S.build(wire, now=NOW, also=0)
    digest.story.image = ""
    post = render.build(digest, translator=translator, when=NOW)
    assert post.has_photo
    assert post.messages[0].image.endswith("assets/cover.png")
    assert pathlib.Path(post.messages[0].image).exists()


def test_the_cover_can_be_pointed_elsewhere_and_switched_off(wire, translator, tmp_path):
    digest = S.build(wire, now=NOW, also=0)
    digest.story.image = ""
    mine = tmp_path / "mine.png"
    mine.write_bytes(b"\x89PNG\r\n\x1a\n")
    post = render.build(digest, translator=translator, when=NOW, cover=str(mine))
    assert post.messages[0].image == str(mine)
    bare = render.build(digest, translator=translator, when=NOW, cover=str(tmp_path / "no.png"))
    assert not bare.has_photo
    assert bare.messages[0].kind == "text"


def test_the_also_block_lists_other_desks_and_links(digest, translator):
    post = render.build(digest, translator=translator, when=NOW)
    block = plain(post.messages[-1].text)
    assert "امروز در یک نگاه" in block and "Also today" in block
    for entry in digest.also:
        assert entry.title[:40] in block
    assert "</a>" in post.messages[-1].text


def test_a_quiet_day_still_gets_a_useful_post():
    from secwire import tips

    post = render.build_tip(index=3, when=NOW)
    assert len(post.messages) == 2
    assert post.tip == 3
    text = plain(post.messages[0].text)
    assert "نکتهٔ امنیتی امروز" in text
    assert tips.get(3)[0].split(".")[0][:20] in text or tips.get(3)[1][:20] in text
    assert tips.count() >= 28, "a month of quiet days without repeating"


def test_the_tip_of_a_given_day_is_always_the_same_tip():
    first = render.build_tip(when=NOW)
    second = render.build_tip(when=datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc))
    assert first.tip == second.tip


def test_the_preview_page_shows_every_message(digest, translator):
    post = render.build(digest, translator=translator, when=NOW)
    page = render.preview_html(post, "test")
    assert page.startswith("<!doctype html>")
    for message in post.messages:
        assert message.text.split("\n")[0][:20] in page
    assert page.count('class="bubble"') == len(post.messages)


# --------------------------------------------------------------------------- translate


def test_translations_are_cached_so_a_headline_is_paid_for_once(tmp_path):
    calls = []

    class Counter(FXMOD.FixtureOpener):
        def __call__(self, request, timeout=25):
            calls.append(request)
            return super().__call__(request, timeout)

    translator = TR.Translator(cache=tmp_path / "fa.json", transport=Counter())
    first = translator.to_persian("CISA Adds One Known Exploited Vulnerability to Catalog")
    second = translator.to_persian("CISA Adds One Known Exploited Vulnerability to Catalog")
    assert first and first == second
    assert len(calls) == 1, "the second ask came from the cache"
    translator.save()
    again = TR.Translator(cache=tmp_path / "fa.json", transport=Counter())
    assert again.to_persian("CISA Adds One Known Exploited Vulnerability to Catalog") == first


def test_an_endpoint_that_echoes_english_is_not_a_translation():
    class Echo:
        def __call__(self, request, timeout=25):
            import urllib.parse

            query = urllib.parse.parse_qs(urllib.parse.urlparse(request).query)["q"][0]
            return json.dumps([[[query, "en", None, None, 1]]]).encode()

    translator = TR.Translator(transport=Echo())
    assert translator.to_persian("Five words of English here") is None
    assert translator.failures == 1


def test_a_dead_endpoint_falls_through_to_the_next_one():
    class Dead:
        def __call__(self, request, timeout=25):
            raise OSError("connection reset")

    translator = TR.Translator(transport=Dead())
    assert translator.to_persian("CISA Adds One Known Exploited Vulnerability") is None
    assert translator.calls, "it tried, and did not raise"
    assert all(value == 1 for value in translator.calls.values())


def test_translation_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("SECWIRE_TRANSLATE", "0")
    translator = TR.Translator(transport=FXMOD.FixtureOpener())
    assert translator.to_persian("CISA Adds One Known Exploited Vulnerability") is None
    assert translator.enabled is False


def test_a_custom_endpoint_is_tried_first(monkeypatch):
    monkeypatch.setenv("SECWIRE_TRANSLATE_URL", "https://my.own/translate?q={q}&to=fa")

    class Mine:
        def __call__(self, request, timeout=25):
            assert request.startswith("https://my.own/translate?q=")
            return json.dumps({"translatedText": "ترجمهٔ خودم"}).encode()

    translator = TR.Translator(transport=Mine())
    assert translator.to_persian("Anything at all here") == "ترجمهٔ خودم"
    assert "custom" in translator.calls


# --------------------------------------------------------------------------- state


def test_the_memory_round_trips_and_keeps_itself_to_itself(home):
    seen = ST.Seen.load(home)
    assert len(seen) == 0
    seen.remember(FXMOD.entries()[0][0])
    path = seen.save()
    assert_private(path)
    again = ST.Seen.load(home)
    assert len(again) == 1
    assert again.latest()["title"] == FXMOD.entries()[0][0].title


def test_a_corrupt_memory_does_not_cost_a_day(home):
    (home / "seen.json").write_text("{not json at all", encoding="utf-8")
    seen = ST.Seen.load(home)
    assert len(seen) == 0
    seen.remember(FXMOD.entries()[0][0])
    seen.save()
    assert len(ST.Seen.load(home)) == 1


def test_old_stories_fall_out_of_the_memory(home):
    seen = ST.Seen.load(home)
    entry = FXMOD.entries()[0][0]
    seen.remember(entry)
    seen.rows[0]["at"] = "2020-01-01T00:00:00+00:00"
    assert seen.prune() == 1
    assert len(seen) == 0


def test_the_preview_inlines_the_cover_so_it_works_with_no_network(digest, translator):
    post = render.build(digest, translator=translator, when=NOW)
    page = render.preview_html(post)
    assert "data:image/png;base64," in page, "the cover travels inside the page"
    assert "src=\"http" not in page, "nothing on the page needs the internet"


def test_a_real_article_photograph_stays_a_url_in_the_preview(digest, translator):
    digest.story.image = "https://cdn.example.com/story.jpg"
    post = render.build(digest, translator=translator, when=NOW)
    page = render.preview_html(post)
    assert 'src="https://cdn.example.com/story.jpg"' in page
    assert "data:image" not in page
