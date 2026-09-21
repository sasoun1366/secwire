"""Delivery and the command line: the wire, and the thing the schedule runs."""

from __future__ import annotations

import json
import pathlib

import pytest

from _helpers import plain

from conftest import FROZEN
from secwire import cli, render, story as S, telegram as TG
from secwire.sources import BY_KEY, Entry

CHAT = "@luyavaai"


def post_for(digest):
    return render.build(digest, when=FROZEN)


class Picky(TG.Transport):
    """A Telegram that refuses photographs and accepts text, like the real one can."""

    def __init__(self):
        self.calls = []

    def call(self, method, payload, files=None):
        self.calls.append((method, payload, files))
        if method == "sendPhoto":
            raise TG.TelegramError("sendPhoto: wrong file identifier/HTTP URL specified")
        return {"ok": True, "result": {"message_id": len(self.calls)}}


def test_a_refused_photograph_does_not_cost_the_post(digest):
    transport = Picky()
    result = TG.deliver(transport, CHAT, post_for(digest))
    methods = [call[0] for call in transport.calls]
    assert methods[0] == "sendPhoto"
    assert methods.count("sendMessage") == len(post_for(digest).messages)
    assert "caption" in result["sent"]


def test_a_url_is_offered_to_telegram_and_a_file_is_uploaded(tmp_path):
    reference, files = TG.photo_payload("https://example.com/a.jpg")
    assert reference == "https://example.com/a.jpg" and files is None
    mine = tmp_path / "cover.png"
    mine.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    reference, files = TG.photo_payload(str(mine))
    assert reference is None
    name, (filename, blob) = next(iter(files.items()))
    assert filename == "cover.png" and blob.startswith(b"\x89PNG")
    with pytest.raises(TG.TelegramError):
        TG.photo_payload(str(tmp_path / "gone.png"))


def test_the_upload_body_is_a_well_formed_multipart(tmp_path):
    blob = tmp_path / "cover.png"
    blob.write_bytes(b"\x89PNG\r\n\x1a\n")
    body, boundary = TG._multipart({"chat_id": "@x", "caption": "hi"},
                                   {"photo": ("cover.png", blob.read_bytes())})
    text = body.decode("utf-8", "replace")
    assert boundary in text
    assert 'name="chat_id"' in text and "@x" in text
    assert 'filename="cover.png"' in text
    assert "Content-Type: image/png" in text
    assert text.rstrip().endswith("--%s--" % boundary)


def test_a_long_message_is_cut_on_a_line_boundary():
    text = "\n".join("line %d %s" % (index, "x" * 60) for index in range(90))
    parts = TG.split_text(text, limit=500)
    assert len(parts) > 1
    assert all(len(part) <= 500 for part in parts)
    assert "\n".join(parts) == text, "nothing is lost in the cut"
    assert TG.split_text("short", limit=500) == ["short"]


def test_the_dry_run_keeps_everything_it_would_have_sent(digest):
    transport = TG.RecordingTransport()
    result = TG.deliver(transport, "@dry", post_for(digest), dry_run=True)
    assert result["ok"]
    assert transport.calls[0]["method"] == "sendPhoto"
    assert transport.calls[0]["files"], "the cover travels as a file, not a URL"
    assert all(call["payload"]["parse_mode"] == "HTML" for call in transport.calls)


@pytest.mark.parametrize("value,expected", [
    ("-1003952166103", -1003952166103),
    ("@luyavaai", "@luyavaai"),
    ("  -1003952166103 ", -1003952166103),
    ("", None),
    (None, None),
])
def test_a_channel_id_is_read_the_way_people_type_it(value, expected):
    assert TG.chat_id_from(value) == expected


# --------------------------------------------------------------------------- cli


def test_the_schedule_maths_is_the_whole_point():
    assert cli._cron_for(10, 0, "+3:30") == "30 6 * * *", "10:00 in Tehran is 06:30 UTC"
    assert cli._cron_for(10, 0, "+0") == "0 10 * * *"
    assert cli._cron_for(9, 30, "-5") == "30 14 * * *"
    assert cli.DEFAULT_CRON == cli._cron_for(10, 0, "+3:30")


def test_sources_lists_the_desk(capsys):
    assert cli.main(["sources"]) == 0
    out = capsys.readouterr().out
    assert "CISA" in out and "Krebs" in out
    for key in ("cisakev", "krebs", "thn", "bleeping", "record", "secweek", "darkread", "sansisc"):
        assert key in out


def test_digest_offline_ranks_and_explains(capsys):
    assert cli.main(["digest", "--offline", "--limit", "5", "--explain"]) == 0
    out = capsys.readouterr().out
    assert "what is on the wire" in out
    assert "relevance" in out
    assert out.count("\n") > 5


def test_digest_json_is_machine_readable(capsys):
    assert cli.main(["digest", "--offline", "--json", "--limit", "3"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 3
    assert {"title", "link", "source", "score", "why", "image"} <= set(rows[0])
    assert rows[0]["score"] >= rows[1]["score"]


def test_the_sample_shows_exactly_what_would_be_sent(capsys):
    assert cli.main(["sample"]) == 0
    out = capsys.readouterr().out
    assert "offline sample (nothing is sent)" in out
    assert "PHOTO + CAPTION" in out
    assert "🏷" in out and "@luyavaai" in out


def test_the_sample_without_a_photograph(capsys):
    assert cli.main(["sample", "--no-photo"]) == 0
    out = capsys.readouterr().out
    assert "PHOTO + CAPTION" not in out
    assert "TEXT [fa]" in out


def test_preview_writes_a_page(tmp_path, capsys):
    out = tmp_path / "preview.html"
    assert cli.main(["preview", "--out", str(out)]) == 0
    page = out.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    assert "@luyavaai" in page
    assert "class=\"bubble\"" in page


def test_tip_list_and_one_tip(capsys):
    assert cli.main(["tip", "--list"]) == 0
    listed = capsys.readouterr().out
    assert "the fallback desk" in listed
    assert cli.main(["tip", "--index", "0"]) == 0
    one = capsys.readouterr().out
    assert "نکتهٔ امنیتی امروز" in one and "#0" in one


def test_doctor_offline_is_honest_about_a_missing_bot(capsys, home, monkeypatch):
    for name in ("SECWIRE_TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN", "SECWIRE_CHAT_ID",
                 "TELEGRAM_CHAT_ID", "SECWIRE_CHANNEL", "SECWIRE_TRANSLATE_URL"):
        monkeypatch.delenv(name, raising=False)
    code = cli.main(["doctor", "--offline"])
    out = capsys.readouterr().out
    assert code == 1
    assert "bot token" in out and "MISSING" in out
    assert "offline fixtures" in out


def test_doctor_is_happy_when_everything_is_there(capsys, home, monkeypatch):
    monkeypatch.setenv("SECWIRE_TELEGRAM_TOKEN", "123456:AAbbbbbbbbbbbbbb")
    monkeypatch.setenv("SECWIRE_CHAT_ID", "@luyavaai")
    assert cli.main(["doctor", "--offline"]) == 0
    out = capsys.readouterr().out
    assert "translation" in out
    assert "all good" in out


def test_post_dry_run_needs_no_token_and_remembers_nothing(capsys, home, monkeypatch):
    monkeypatch.delenv("SECWIRE_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert cli.main(["post", "--offline", "--dry-run", "--channel", "@luyavaai"]) == 0
    out = capsys.readouterr().out
    assert "daily post" in out
    assert "message(s)" in out
    assert not (home / "seen.json").exists(), "a dry run must not spend the story"


def test_post_without_a_channel_fails_loudly(home, monkeypatch, capsys):
    monkeypatch.setenv("SECWIRE_TELEGRAM_TOKEN", "123456:AAbbbbbbbbbbbbbb")
    for name in ("SECWIRE_CHAT_ID", "TELEGRAM_CHAT_ID", "SECWIRE_CHANNEL"):
        monkeypatch.delenv(name, raising=False)
    code = cli.main(["post", "--offline"])
    assert code == 1
    assert "no channel" in capsys.readouterr().err


def test_nothing_new_posts_a_tip_instead(wire, home, capsys):
    from secwire import state as ST

    seen = ST.Seen.load(home)
    for item in wire:
        seen.remember(item)
    seen.save()
    assert cli.main(["post", "--offline", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "tip of the day" in out


def test_nothing_new_with_no_tip_says_so_and_exits_three(wire, home):
    from secwire import state as ST

    seen = ST.Seen.load(home)
    for item in wire:
        seen.remember(item)
    seen.save()
    assert cli.main(["post", "--offline", "--dry-run", "--no-tip"]) == 3


def test_version_and_help():
    assert cli.main(["version"]) == 0
    assert cli.main([]) == 2


def test_a_story_from_one_desk_is_never_listed_twice_in_the_also_block():
    left = Entry("A", "https://a.example/1", source=BY_KEY["thn"])
    right = Entry("B", "https://a.example/2", source=BY_KEY["thn"])
    digest = S.build([left, right], also=3)
    assert digest.also == []
