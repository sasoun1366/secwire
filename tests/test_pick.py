"""Choosing the story: the ranking has to be explainable, and never repeat itself."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import FROZEN

from secwire import sources as SD
from secwire import state as ST
from secwire import story as S
from secwire import text as T

NOW = FROZEN


def entry(title, summary="", desk="thn", hours=2, image=""):
    source = SD.BY_KEY[desk]
    return SD.Entry(title, "https://%s/%s" % (desk, T.strip_html(title)[:20].replace(" ", "-")),
                    summary=summary, published=NOW - timedelta(hours=hours), source=source,
                    image=image)


def test_an_exploited_vulnerability_beats_a_product_launch():
    real = entry("Cisco zero-day exploited in the wild, patch now",
                 "Attackers are exploiting CVE-2026-1 in the wild.")
    noise = entry("Vendor unveils new platform at RSA, register now for the webinar",
                  "The company announced a partnership and a new dashboard.")
    assert S.relevance(real) > S.relevance(noise)
    assert S.score(real, NOW)[0] > S.score(noise, NOW)[0]


def test_fresh_beats_stale_when_the_rest_is_equal():
    fresh = entry("Router firmware flaw lets attackers in", "A flaw in the firmware.")
    stale = entry("Router firmware flaw lets attackers in", "A flaw in the firmware.",
                  hours=96)
    assert S.score(fresh, NOW)[0] > S.score(stale, NOW)[0]
    reasons = S.score(stale, NOW)[1]
    assert any("old" in reason for reason in reasons)


def test_the_score_explains_itself():
    total, reasons = S.score(entry("CVE-2026-1 patch for the VPN", "actively exploited"), NOW)
    assert total > 0
    assert any("relevance" in reason for reason in reasons)
    assert any("desk" in reason for reason in reasons)


def test_categories_and_advice_line_up():
    cases = {
        "vulnerability": "CISA adds a vulnerability to the KEV catalog after exploitation",
        "ransomware": "Ransomware gang demands an extortion payment after the breach",
        "phishing": "Phishing kit harvests credentials through a fake login page",
        "network": "MikroTik router firmware bug exposes the firewall",
        "malware": "A new infostealer loader drops a backdoor on Windows hosts",
        "breach": "Data breach exposes millions of records",
        "policy": "Court order forces a company to change its privacy policy",
    }
    for expected, headline in cases.items():
        assert S.classify(entry(headline)) == expected, headline
    for key in cases:
        fa, en = S.advice(key)
        assert len(fa) > 40 and len(en) > 40
        cat_fa, cat_en = S.category_labels(key)
        assert cat_fa and cat_en


def test_one_story_reported_twice_is_one_story():
    first = entry("ShinyHunters takes over Cl0p ransomware site, demands payment")
    second = entry("ShinyHunters hijacks Cl0p ransomware site and demands payment")
    other = entry("Microsoft reminds admins to migrate Entra ID users to passkeys")
    assert S.same_story(first, second)
    assert not S.same_story(first, other)
    assert S.identity(first) == S.identity(first)


def test_ranking_is_stable_and_the_also_list_has_no_twins(wire):
    digest = S.build(wire, now=NOW, also=3)
    assert not digest.empty
    assert digest.story.score >= digest.also[0].score
    titles = [digest.story] + list(digest.also)
    for index, left in enumerate(titles):
        for right in titles[index + 1:]:
            assert not S.same_story(left, right)
    desks = [e.source.key for e in digest.also if e.source]
    assert len(desks) == len(set(desks)), "one desk, one line"
    assert S.build(wire, now=NOW, also=3).story.link == digest.story.link


def test_what_was_posted_is_not_posted_again(wire, tmp_path):
    seen = ST.Seen(path=tmp_path / "seen.json")
    first = S.build(wire, now=NOW, also=3)
    seen.remember(first.story)
    for also in first.also:
        seen.remember(also, kind="also")
    assert seen.knows(first.story)
    second = S.build(wire, now=NOW, seen=seen, also=3)
    assert not second.empty
    assert second.story.link != first.story.link
    assert all(not seen.knows(e) for e in second.also if e.link != first.story.link)


def test_a_day_with_nothing_new_is_empty_not_a_crash(wire, tmp_path):
    seen = ST.Seen(path=tmp_path / "seen.json")
    for item in wire:
        seen.remember(item)
    assert S.build(wire, now=NOW, seen=seen).empty


def test_the_ranking_keeps_the_wire_quiet_about_noise(wire):
    ranked = S.rank(wire, now=NOW, limit=len(wire))
    top = ranked[0]
    assert "webinar" not in top.title.lower()
    assert top.score > ranked[-1].score
