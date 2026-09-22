"""One post a day: the guard, the day's edges, and the way out of it.

The job runs twice a morning — ten o'clock, and a backup tick for the mornings
GitHub's scheduler runs late or drops a run. Whoever gets there first owns the
day; the second run must find the channel already spoken for and go home quietly
instead of saying the news twice. That is what these tests pin down.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from secwire import cli, state as ST, telegram as TG


class Desk(TG.RecordingTransport):
    """A transport that goes nowhere, remembers everything, and can be told to refuse."""

    def __init__(self):
        super().__init__(echo=False)
        self.refuse = ""                      # a method name, or "*" for everything

    def describe(self) -> str:
        return "the test desk"

    def call(self, method, payload, files=None):
        if self.refuse in (method, "*"):
            raise TG.TelegramError("%s refused by the test" % method)
        return super().call(method, payload, files=files)

    # what the channel was told, in order
    def methods(self):
        return [call["method"] for call in self.calls]

    def posts(self):
        return [m for m in self.methods() if m in ("sendMessage", "sendPhoto")]


def wire_it_up(monkeypatch, home, desk):
    """Offline feeds, a channel, and a transport that goes nowhere."""
    monkeypatch.setenv("SECWIRE_HOME", str(home))
    monkeypatch.setenv("SECWIRE_TELEGRAM_TOKEN", "123456:AAbbbbbbbbbbbbbb")
    monkeypatch.setenv("SECWIRE_CHAT_ID", "-1003952166103")
    monkeypatch.setattr(cli.telegram, "HttpTransport", lambda token: desk)
    return desk


# --------------------------------------------------------------------------- the day


def test_the_two_morning_ticks_are_the_same_tehran_day():
    # 06:30 UTC (the ten o'clock post), 08:00 UTC (the backup tick), and even a badly
    # late 20:00 UTC run all belong to one Tehran day.
    for hour, minute in ((6, 30), (8, 0), (20, 0)):
        when = datetime(2026, 9, 22, hour, minute, tzinfo=timezone.utc)
        assert ST.post_day(when) == "2026-09-22", when
    # …and the edge is Tehran midnight, which is 20:30 UTC the day before.
    assert ST.post_day(datetime(2026, 9, 22, 20, 29, tzinfo=timezone.utc)) == "2026-09-22"
    assert ST.post_day(datetime(2026, 9, 22, 20, 31, tzinfo=timezone.utc)) == "2026-09-23"


def test_a_day_is_remembered_and_read_back(home):
    seen = ST.Seen.load(home)
    assert not seen.posted_on()
    seen.mark_posted(datetime(2026, 9, 22, 6, 30, tzinfo=timezone.utc))
    seen.save()

    again = ST.Seen.load(home)
    assert again.posted_on(datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc))
    assert not again.posted_on(datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc))
    assert again.last_post_day() == "2026-09-22"


def test_marking_the_same_day_twice_does_not_grow_the_file(home):
    seen = ST.Seen.load(home)
    for _ in range(5):
        seen.mark_posted(datetime(2026, 9, 22, 6, 30, tzinfo=timezone.utc))
    assert seen.posts == ["2026-09-22"]


def test_the_day_list_is_pruned_to_a_month(home):
    seen = ST.Seen.load(home)
    when = datetime(2026, 1, 1, 6, 30, tzinfo=timezone.utc)
    for day in range(60):
        seen.mark_posted(when + timedelta(days=day))
    assert len(seen.posts) == 60
    seen.prune(now=when + timedelta(days=60))
    assert len(seen.posts) == ST.KEEP_POSTS
    assert seen.posts[-1] == ST.post_day(when + timedelta(days=59))


def test_a_memory_written_by_an_older_build_still_answers_the_question(home):
    """The day a story was remembered is the day the post went out."""
    (home / "seen.json").write_text(
        '{"version": 1, "entries": [{"id": "x", "title": "T", "link": "l",'
        ' "source": "thn", "kind": "story", "at": "%sT06:31:00+00:00"}]}'
        % ST.post_day(), encoding="utf-8")
    seen = ST.Seen.load(home)
    assert seen.posts == []
    assert seen.posted_on(), "today's memory has no day list, but it still knows"
    assert not seen.posted_on(datetime.now(timezone.utc) + timedelta(days=1))


def test_a_memory_file_from_before_the_day_list_still_loads(home):
    (home / "seen.json").write_text(
        '{"version": 1, "entries": [{"id": "x", "title": "T", "link": "l",'
        ' "source": "thn", "kind": "story", "at": "2026-09-21T06:30:00+00:00"}]}',
        encoding="utf-8")
    seen = ST.Seen.load(home)
    assert len(seen) == 1
    assert seen.posts == []
    assert not seen.posted_on(datetime(2026, 9, 22, 6, 30, tzinfo=timezone.utc))


# ------------------------------------------------------------------------ the guard


def test_the_second_run_of_the_day_posts_nothing(monkeypatch, home, capsys):
    desk = wire_it_up(monkeypatch, home, Desk())

    assert cli.main(["post", "--offline"]) == 0
    assert "posted" in capsys.readouterr().out
    after_first = len(desk.posts())
    assert after_first, "the first run has to reach the channel"

    assert cli.main(["post", "--offline"]) == 0, "the backup tick exits green, not red"
    assert "already has its post" in capsys.readouterr().out
    assert len(desk.posts()) == after_first, "nothing new may reach the channel"


def test_the_guard_holds_when_the_day_came_from_a_tip(monkeypatch, home, capsys):
    desk = wire_it_up(monkeypatch, home, Desk())

    seen = ST.Seen.load(home)
    seen.mark_posted(datetime.now(timezone.utc))
    seen.save()

    assert cli.main(["post", "--offline"]) == 0
    assert "already has its post" in capsys.readouterr().out
    assert not desk.posts()


def test_force_is_the_way_out(monkeypatch, home, capsys):
    desk = wire_it_up(monkeypatch, home, Desk())

    seen = ST.Seen.load(home)
    seen.mark_posted(datetime.now(timezone.utc))
    seen.save()

    assert cli.main(["post", "--offline", "--force"]) == 0
    assert "posted" in capsys.readouterr().out
    assert desk.posts()


def test_a_dry_run_is_never_blocked_and_never_spends_the_day(monkeypatch, home, capsys):
    desk = wire_it_up(monkeypatch, home, Desk())

    seen = ST.Seen.load(home)
    seen.mark_posted(datetime.now(timezone.utc))
    seen.save()
    before = (home / "seen.json").read_text(encoding="utf-8")

    assert cli.main(["post", "--offline", "--dry-run"]) == 0
    assert "already has its post" not in capsys.readouterr().out
    assert not desk.posts()
    assert (home / "seen.json").read_text(encoding="utf-8") == before, "a dry run changes nothing"


def test_yesterday_does_not_block_today(monkeypatch, home, capsys):
    desk = wire_it_up(monkeypatch, home, Desk())

    seen = ST.Seen.load(home)
    seen.mark_posted(datetime.now(timezone.utc) - timedelta(days=1))
    seen.save()

    assert cli.main(["post", "--offline"]) == 0
    assert capsys.readouterr().out.count("already has its post") == 0
    assert desk.posts()


def test_the_day_is_not_spent_when_the_post_fails(monkeypatch, home):
    desk = wire_it_up(monkeypatch, home, Desk())
    desk.refuse = "*"

    with pytest.raises(TG.TelegramError):
        cli.main(["post", "--offline"])
    assert not ST.Seen.load(home).posted_on(), "a failed post must not eat the day"


def test_the_successful_run_says_which_day_it_claimed(monkeypatch, home, capsys):
    desk = wire_it_up(monkeypatch, home, Desk())
    assert cli.main(["post", "--offline"]) == 0
    assert "posted on %s" % ST.post_day() in capsys.readouterr().out
