"""The command line: what a person runs, and what the schedule runs.

Reading the feeds is one command, posting the day's story is another, and seeing
exactly what would be posted is a third that touches nothing. The daily job in CI
runs `secwire post`, which is the same thing a human runs — there is no separate
"automation mode" to drift out of step with the tool.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from . import __version__
from . import fixtures as FX
from . import render, state, story as S, telegram
from .render import Post
from .sources import SOURCES, BY_KEY, Entry, collect, enrich, within
from .translate import Translator

WIDTH = 78
DEFAULT_CHANNEL = render.DEFAULT_CHANNEL
#: 10:00 in Tehran (UTC+3:30, no daylight saving since 2022) is 06:30 UTC, which is
#: what GitHub's cron speaks. See `secwire schedule` for other time zones.
DEFAULT_CRON = "30 6 * * *"


class Reporter:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.step_number = 0

    def banner(self, text: str) -> None:
        if self.quiet:
            return
        print("secwire %s — %s" % (__version__, text))
        print("─" * WIDTH)

    def step(self, text: str, note: str = "") -> None:
        if self.quiet:
            return
        self.step_number += 1
        left = "%2d. %s" % (self.step_number, text)
        if note:
            pad = max(1, WIDTH - len(left) - len(note) - 2)
            print("%s %s%s" % (left, "·" * min(pad, 24) + " ", note))
        else:
            print(left)

    def say(self, text: str = "") -> None:
        if not self.quiet:
            print(text)

    def warn(self, text: str) -> None:
        print("   ! %s" % text, file=sys.stderr)


# --------------------------------------------------------------------------- helpers


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return ""


def token_from_env() -> str:
    return _env("SECWIRE_TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN")


def chat_from_env() -> Optional[object]:
    return telegram.chat_id_from(_env("SECWIRE_CHAT_ID", "TELEGRAM_CHAT_ID", "SECWIRE_CHANNEL"))


def _gather(args, reporter: Reporter) -> Tuple[List[Entry], List[str], object]:
    """Read the feeds, or the bundled pages when --offline was asked for."""
    if getattr(args, "offline", False):
        entries, errors = FX.entries()
        reporter.step("offline: reading the bundled pages", "%d items" % len(entries))
        if not entries:
            raise SystemExit("no fixtures found — run from a checkout of the repository")
        return entries, errors, FX.FixtureOpener()

    opener = None
    entries, errors = collect(timeout=getattr(args, "timeout", 25), opener=opener)
    reporter.step("reading %d feeds" % len(SOURCES), "%d items, %d complaints"
                  % (len(entries), len(errors)))
    for complaint in errors:
        reporter.warn(complaint)
    if not entries:
        raise SystemExit("no feed answered — nothing to work with")
    return entries, errors, None


def _translator(args, root: pathlib.Path) -> Optional[Translator]:
    if getattr(args, "no_translate", False):
        return None
    cache = root / "cache" / "fa.json"
    if getattr(args, "offline", False):
        return Translator(cache=cache, transport=FX.FixtureOpener())
    return Translator(cache=cache)


def _pick(args, entries, seen, reporter: Reporter, now: datetime):
    fresh = entries if getattr(args, "include_old", False) else within(entries, now=now, days=4)
    digest = S.build(fresh, now=now, seen=seen, also=getattr(args, "also", 3))
    if digest.empty:
        reporter.step("story of the day", "nothing new — falling back to a tip")
        return digest
    reporter.step("story of the day", "%s (score %.1f)" % (digest.story.source.key if digest.story.source else "?",
                                                           digest.story.score))
    reporter.say("      %s" % digest.story.title)
    if getattr(args, "explain", False):
        reporter.say("      %s" % digest.story.why)
    return digest


# --------------------------------------------------------------------------- commands


def cmd_sources(args) -> int:
    print("the desk — %d sources" % len(SOURCES))
    print("─" * WIDTH)
    for source in SOURCES:
        print("%-9s %-38s weight %2d" % (source.key, source.name, source.weight))
        print("          %s" % source.url)
    return 0


def cmd_digest(args) -> int:
    reporter = Reporter(args.quiet or args.json)
    reporter.banner("what is on the wire")
    now = datetime.now(timezone.utc)
    entries, errors, _opener = _gather(args, reporter)
    seen = state.Seen.load() if args.respect_seen else None
    rows = S.rank(entries, now=now, seen=seen, limit=args.limit)
    reporter.step("ranked by freshness, relevance and desk", "%d shown" % len(rows))
    if args.json:
        print(json.dumps(
            [
                {
                    "title": e.title,
                    "link": e.link,
                    "source": e.source.key if e.source else "",
                    "published": e.published.isoformat() if e.published else "",
                    "score": round(e.score, 1),
                    "why": e.why,
                    "image": bool(e.image),
                }
                for e in rows
            ],
            ensure_ascii=False,
            indent=1,
        ))
        return 0
    print()
    for index, entry in enumerate(rows, 1):
        desk = entry.source.key if entry.source else "?"
        stamp = entry.published.strftime("%Y-%m-%d %H:%M") if entry.published else "   no date "
        print("%2d. %5.1f  %-9s %s" % (index, entry.score, desk, stamp))
        print("      %s" % entry.title)
        if args.explain:
            print("      %s" % entry.why)
    if errors and not args.quiet:
        print("\n%d source complaint(s): see above" % len(errors))
    return 0


def _make_post(args, reporter: Reporter, now: datetime):
    root = state.home()
    entries, errors, opener = _gather(args, reporter)
    seen = state.Seen.load(root)
    digest = _pick(args, entries, seen, reporter, now)

    translator = _translator(args, root)
    if digest.empty:
        if args.no_tip:
            reporter.step("nothing to post", "and --no-tip was given")
            return None, seen, translator, None
        post = render.build_tip(translator=translator, when=now, channel=args.tag)
        reporter.step("tip of the day", "#%d" % post.tip)
        return post, seen, translator, None

    story = digest.story
    if not args.no_enrich and not args.no_photo:
        before = len(story.summary)
        enrich(story, opener=opener)
        note = "photograph: %s" % ("yes" if story.image else "none")
        if len(story.summary) > before:
            note += ", longer summary"
        reporter.step("reading the article", note)
    post = render.build(digest, translator=translator, when=now, photo=not args.no_photo,
                        also=not args.no_also, channel=args.tag)
    return post, seen, translator, digest


def cmd_post(args) -> int:
    reporter = Reporter(args.quiet)
    reporter.banner("daily post")
    now = datetime.now(timezone.utc)
    post, seen, translator, digest = _make_post(args, reporter, now)
    if post is None:
        return 3

    chat_id = args.chat or chat_from_env()
    if args.dry_run:
        transport = telegram.RecordingTransport(echo=not args.quiet)
        if not chat_id:
            chat_id = "@dry-run"
    else:
        if not chat_id:
            return _fail("no channel: set SECWIRE_CHAT_ID, or pass --channel")
        transport = telegram.HttpTransport(token_from_env())
        reporter.step("talking to Telegram", transport.describe())

    result = telegram.deliver(transport, chat_id, post, dry_run=args.dry_run)
    reporter.step("posted %d message(s) to %s" % (len(result["sent"]), chat_id),
                  ", ".join(result["sent"]))

    if args.dry_run:
        print()
        _print_messages(post)
    else:
        for entry in ([post.story] if post.story else []) + (digest.also if digest else []):
            if entry:
                seen.remember(entry, kind="story" if entry is post.story else "also")
        seen.prune()
        path = seen.save()
        reporter.step("remembered", "%d stories in %s" % (len(seen), path))

    if translator is not None:
        translator.save()
        if not args.quiet:
            reporter.say("      %s" % translator.stats())
    if args.json:
        print(json.dumps({"ok": True, "sent": result["sent"], "dry_run": args.dry_run,
                          "story": post.story.title if post.story else "",
                          "category": post.category}, ensure_ascii=False))
    return 0


def cmd_sample(args) -> int:
    """Exactly what goes to the channel, from the bundled pages, with nothing sent."""
    args.offline = True
    args.dry_run = True
    args.quiet = getattr(args, "quiet", False)
    reporter = Reporter(quiet=True)
    now = args.when or datetime.now(timezone.utc)
    post, _seen, _translator, digest = _make_post(args, reporter, now)
    if post is None:
        return 3
    print("secwire %s — offline sample (nothing is sent)" % __version__)
    print("─" * WIDTH)
    if post.story:
        print("story   : %s" % post.story.title)
        print("desk    : %s" % (post.story.source.name if post.story.source else "?"))
        print("category: %s" % post.category)
        print("photo   : %s" % ("yes" if post.has_photo else "no"))
    print("─" * WIDTH)
    _print_messages(post)
    return 0


def _print_messages(post: Post) -> None:
    for index, message in enumerate(post.messages, 1):
        kind = "PHOTO + CAPTION" if message.kind == "photo" else "TEXT"
        print("#%d %s [%s] — %d characters%s" % (
            index, kind, message.label or "-", len(message.text),
            "  (limit %d)" % render.CAPTION_LIMIT if message.kind == "photo" else ""))
        if message.kind == "photo":
            print("photo url: %s" % message.image)
        print("┈" * WIDTH)
        print(_plain(message.text))
        print()


def _plain(html: str) -> str:
    """Telegram HTML as a person reads it — for the terminal output only."""
    import html as _h
    import re as _re

    text = _h.unescape(html)
    text = _re.sub(r"<a href=\"([^\"]+)\">([^<]*)</a>", lambda m: "%s (%s)" % (m.group(2), m.group(1)), text)
    return _re.sub(r"</?[^>]+>", "", text)


def cmd_preview(args) -> int:
    args.offline = True
    args.no_enrich = getattr(args, "no_enrich", False)
    reporter = Reporter(quiet=True)
    now = args.when or datetime.now(timezone.utc)
    post, _seen, _translator, _digest = _make_post(args, reporter, now)
    if post is None:
        return 3
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render.preview_html(post, "secwire — tomorrow's post, rendered offline"),
                   encoding="utf-8")
    print("wrote %s (%d bytes)" % (out, out.stat().st_size))
    return 0


def cmd_tip(args) -> int:
    from . import tips

    if args.list:
        print("the fallback desk — %d tips" % tips.count())
        print("─" * WIDTH)
        for index, line in tips.as_rows():
            print("%3d. %s" % (index, line))
        return 0
    now = datetime.now(timezone.utc)
    post = render.build_tip(index=args.index, when=now, channel=args.tag)
    if args.post:
        return _post_tip(args, post)
    print("tip #%s" % post.tip)
    print("─" * WIDTH)
    _print_messages(post)
    return 0


def _post_tip(args, post: Post) -> int:
    chat_id = args.chat or chat_from_env()
    if args.send:
        transport = telegram.HttpTransport(token_from_env())
        if not chat_id:
            return _fail("no channel: set SECWIRE_CHAT_ID")
    else:
        transport = telegram.RecordingTransport(echo=False)
        chat_id = chat_id or "@dry-run"
    result = telegram.deliver(transport, chat_id, post)
    print("posted %d message(s) to %s: %s" % (len(result["sent"]), chat_id, ", ".join(result["sent"])))
    return 0


def cmd_doctor(args) -> int:
    """Everything the daily job needs, checked one line at a time."""
    problems: List[str] = []
    print("secwire %s — doctor" % __version__)
    print("─" * WIDTH)

    root = state.home()
    print("%-22s %s" % ("state directory", root))

    seen = state.Seen.load(root)
    latest = seen.latest()
    print("%-22s %d stories%s" % ("memory", len(seen),
                                  ", last: %s" % latest["at"] if latest else " (never posted)"))

    token = token_from_env()
    print("%-22s %s" % ("bot token", "present (…%s)" % token[-4:] if token else "MISSING"))
    if not token:
        problems.append("bot token missing: set SECWIRE_TELEGRAM_TOKEN")

    chat_id = chat_from_env()
    print("%-22s %s" % ("channel", chat_id if chat_id else "MISSING"))
    if not chat_id:
        problems.append("channel missing: set SECWIRE_CHAT_ID")

    if args.offline:
        entries, errors = FX.entries()
        print("%-22s %d items from %s" % ("offline fixtures", len(entries), FX.ROOT))
    else:
        entries, errors = collect(timeout=args.timeout)
        good = len({e.source.key for e in entries if e.source})
        print("%-22s %d/%d answered, %d items" % ("feeds", good, len(SOURCES), len(entries)))
        if good < max(2, len(SOURCES) // 3):
            problems.append("too few feeds answered: %d" % good)
    for complaint in errors:
        print("%-22s ! %s" % ("", complaint))

    translator = Translator()
    probe = translator.to_persian("A vulnerability was exploited in the wild.")
    print("%-22s %s" % ("translation", "working" if probe else "unavailable (posts fall back to English)"))

    if token and chat_id and not args.offline:
        transport = telegram.HttpTransport(token)
        try:
            me = telegram.whoami(transport).get("result", {})
            print("%-22s @%s" % ("telegram says", me.get("username", "?")))
            info = telegram.chat_check(transport, chat_id).get("result", {})
            print("%-22s %s (%s)" % ("channel title", info.get("title", "?"), info.get("type", "?")))
        except telegram.TelegramError as exc:
            problems.append("telegram: %s" % exc)
            print("%-22s ! %s" % ("telegram", exc))

    if problems:
        print()
        for problem in problems:
            print("  ! %s" % problem)
        return 1
    print("\nall good — `secwire post` has everything it needs.")
    return 0


def _cron_for(hour: int, minute: int, offset: str) -> str:
    """A local time as a UTC cron line. Offsets arrive as +3:30 or -5."""
    sign = -1 if offset.strip().startswith("-") else 1
    body = offset.strip().lstrip("+-")
    hours, _, minutes = body.partition(":")
    total = int(hours or 0) * 60 + int(minutes or 0)
    utc = (hour * 60 + minute) - sign * total
    utc %= 24 * 60
    return "%d %d * * *" % (utc % 60, utc // 60)


def cmd_schedule(args) -> int:
    cron = _cron_for(args.hour, args.minute, args.tz)
    print("secwire — the daily post, scheduled\n")
    print("local time   : %02d:%02d (%s, offset %s)" % (args.hour, args.minute, args.tz_name, args.tz))
    print("github cron  : %s UTC   ← what .github/workflows/daily.yml uses" % cron)
    print("local cron   : %d %d * * *    (crontab -e, machine time zone)" % (args.minute, args.hour))
    print()
    print("GitHub Actions is the recommended place to run it: the schedule is free,")
    print("the machine is not yours, and the run is logged where you can read it.")
    print()
    print("  1. push this repository to GitHub")
    print("  2. add two repository secrets (Settings → Secrets and variables → Actions):")
    print("       SECWIRE_TELEGRAM_TOKEN   the bot token from @BotFather")
    print("       SECWIRE_CHAT_ID          %s  (or -100… id)" % DEFAULT_CHANNEL)
    print("  3. make sure the bot is an administrator of the channel")
    print("  4. Actions → daily post → Run workflow     ← check it once by hand")
    print()
    print("The job commits state/seen.json back after every post, so it never repeats")
    print("a story. GitHub's scheduler can be a few minutes late at busy times; the")
    print("post still goes out, in the same order, with the same content.")
    print()
    print("On your own machine, if you would rather not use Actions:")
    print()
    print("  Windows   schtasks /create /tn \"secwire\" /sc daily /st %02d:%02d \\" % (args.hour, args.minute))
    print("              /tr \"python -m secwire post\"")
    print("  Linux/mac %d %d * * *  cd /path/to/secwire && python3 -m secwire post >> post.log 2>&1"
          % (args.minute, args.hour))
    print()
    print("  systemd (secwire.timer):")
    print("      [Timer]")
    print("      OnCalendar=*-*-* %02d:%02d:00" % (args.hour, args.minute))
    print("      Persistent=true")
    return 0


def cmd_version(args) -> int:
    print("secwire %s" % __version__)
    print("python %s" % sys.version.split()[0])
    print("sources %d · tips %d" % (len(SOURCES), __import__("secwire.tips", fromlist=["tips"]).count()))
    return 0


def _fail(text: str) -> int:
    print("error: %s" % text, file=sys.stderr)
    return 1


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="secwire",
        description="One network-security story a day, posted to a Telegram channel.",
        epilog="Every command that reads the internet also takes --offline, which reads "
               "the bundled pages instead — same pipeline, no network.",
    )
    parser.add_argument("--version", action="version", version="secwire %s" % __version__)
    subs = parser.add_subparsers(dest="command")

    def shared(sub, offline=False):
        sub.add_argument("--json", action="store_true", help="machine-readable output")
        sub.add_argument("--quiet", action="store_true", help="only the result")
        sub.add_argument("--timeout", type=int, default=25, help="seconds per request")
        sub.add_argument("--offline", action="store_true", default=offline,
                         help="read the bundled pages instead of the internet")

    p = subs.add_parser("sources", help="list the feeds this tool reads")
    p.set_defaults(func=cmd_sources)

    p = subs.add_parser("digest", help="what is on the wire right now, ranked")
    shared(p)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--explain", action="store_true", help="show why each story scored")
    p.add_argument("--respect-seen", action="store_true", help="leave out what was posted")
    p.set_defaults(func=cmd_digest)

    p = subs.add_parser("post", help="choose today's story and publish it")
    shared(p)
    p.add_argument("--dry-run", action="store_true", help="build it, print it, send nothing")
    p.add_argument("--chat", "--channel", dest="chat", default="",
                   help="channel to post to: @name or -100… (default: environment)")
    p.add_argument("--tag", default=DEFAULT_CHANNEL,
                   help="the mention printed at the bottom of every message")
    p.add_argument("--also", type=int, default=3, help="how many other headlines to list")
    p.add_argument("--no-also", action="store_true", help="skip the 'also today' block")
    p.add_argument("--no-photo", action="store_true", help="text only, no photograph")
    p.add_argument("--no-translate", action="store_true", help="English only")
    p.add_argument("--no-tip", action="store_true", help="if nothing is new, post nothing")
    p.add_argument("--no-enrich", action="store_true", help="do not fetch the article page")
    p.add_argument("--include-old", action="store_true", help="ignore the 4-day freshness window")
    p.add_argument("--explain", action="store_true")
    p.set_defaults(func=cmd_post)

    p = subs.add_parser("sample", help="the whole post, offline, printed to the terminal")
    shared(p, offline=True)
    p.add_argument("--also", type=int, default=3)
    p.add_argument("--no-also", action="store_true")
    p.add_argument("--no-photo", action="store_true")
    p.add_argument("--no-translate", action="store_true")
    p.add_argument("--no-enrich", action="store_true")
    p.add_argument("--no-tip", action="store_true")
    p.add_argument("--include-old", action="store_true")
    p.add_argument("--when", default=None, type=_as_datetime, help="pretend it is this day")
    p.set_defaults(func=cmd_sample, dry_run=True)

    p = subs.add_parser("preview", help="write an HTML page that looks like the post")
    shared(p, offline=True)
    p.add_argument("--out", default="docs/preview.html")
    p.add_argument("--also", type=int, default=3)
    p.add_argument("--no-also", action="store_true")
    p.add_argument("--no-photo", action="store_true")
    p.add_argument("--no-translate", action="store_true")
    p.add_argument("--no-enrich", action="store_true")
    p.add_argument("--no-tip", action="store_true")
    p.add_argument("--include-old", action="store_true")
    p.add_argument("--when", default=None, type=_as_datetime)
    p.set_defaults(func=cmd_preview)

    p = subs.add_parser("tip", help="the fallback desk: hygiene tips for quiet days")
    p.add_argument("--list", action="store_true", help="list every tip")
    p.add_argument("--index", type=int, default=None, help="a specific tip")
    p.add_argument("--post", action="store_true", help="post it")
    p.add_argument("--send", action="store_true", help="with --post: really send")
    p.add_argument("--chat", "--channel", dest="chat", default="")
    p.add_argument("--tag", default=DEFAULT_CHANNEL)
    p.set_defaults(func=cmd_tip)

    p = subs.add_parser("doctor", help="check that the daily job has what it needs")
    shared(p)
    p.set_defaults(func=cmd_doctor)

    p = subs.add_parser("schedule", help="the daily post, and where to schedule it")
    p.add_argument("--hour", type=int, default=10)
    p.add_argument("--minute", type=int, default=0)
    p.add_argument("--tz", default="+3:30", help="your UTC offset, e.g. +3:30 or -5")
    p.add_argument("--tz-name", default="Tehran")
    p.set_defaults(func=cmd_schedule)

    p = subs.add_parser("version", help="what this is")
    p.set_defaults(func=cmd_version)
    return parser


def _as_datetime(text: str):
    try:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD or an ISO timestamp") from None


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    if not hasattr(args, "tag"):
        args.tag = DEFAULT_CHANNEL
    try:
        return args.func(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":                                    # pragma: no cover
    sys.exit(main())
