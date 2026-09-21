#!/usr/bin/env python3
"""Freeze a copy of the wire into secwire/fixtures/.

The tool ships with a bundle of real pages so that `--offline`, `preview` and the
test suite all run without a network. This script is how that bundle is made: it
reads the live feeds, keeps the first few items of each, does the same for the
article behind whichever story ranks first, and asks the translation endpoint for
the handful of Persian lines the sample needs.

    python3 tools/make_fixtures.py            # refresh everything
    python3 tools/make_fixtures.py --dry-run  # say what it would write

Run it when the fixtures look stale. It writes files into the repository, so read
the diff before you commit it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from secwire import sources as SD  # noqa: E402
from secwire import story as S  # noqa: E402
from secwire import text as T  # noqa: E402
from secwire.fixtures import ROOT  # noqa: E402
from secwire.translate import Translator  # noqa: E402

ITEMS = 4
FOOTER = ("\n<!-- frozen by tools/make_fixtures.py: the article behind the story this\n"
          "     bundle ranks first, trimmed to its metadata and opening paragraphs -->\n")


def trim_feed(source, keep: int) -> bytes:
    data = SD.fetch(source.url)
    root = ET.fromstring(data)
    parents = list(root.iter())
    for parent in parents:
        children = [c for c in list(parent) if c.tag.rsplit("}", 1)[-1].lower() in ("item", "entry")]
        if children:
            for extra in children[keep:]:
                parent.remove(extra)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def trim_article(url: str) -> bytes:
    """The article page, kept to what secwire reads: the metadata and the opening."""
    page = SD.fetch(url).decode("utf-8", "replace")
    cut = page.lower().find("</head>")
    head = page[: cut + 7] if cut > 0 else page[:20000]
    body = page[cut:] if cut > 0 else ""
    blocks = re.findall(r"<p\b[^>]*>(.*?)</p>", body, re.IGNORECASE | re.DOTALL)
    kept = [T.strip_html(block) for block in blocks]
    kept = [line for line in kept if len(line) > 80][:3]
    paragraphs = "\n".join("<p>%s</p>" % line for line in kept)
    document = (
        "<!doctype html>\n<html>\n<head>"
        + head[head.lower().find("<head>") + 6:].replace("</head>", "").strip()
        + "\n</head>\n<body>%s\n%s\n</body>\n</html>\n" % (FOOTER, paragraphs)
    )
    return document.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep", type=int, default=ITEMS)
    args = parser.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    which: dict = {}
    for source in SD.SOURCES:
        try:
            blob = trim_feed(source, args.keep)
        except SD.FeedError as exc:
            print("  ! %-9s %s" % (source.key, exc))
            continue
        path = ROOT / ("%s.xml" % source.key)
        which[source.key] = len(SD.parse_feed(blob, source))
        print("  %-9s %3d bytes  %d items  %s" % (source.key, len(blob), which[source.key], path.name))
        if not args.dry_run:
            path.write_bytes(blob)

    print("\nranking the frozen wire to find the story the sample will pick…")
    entries: list = []
    for source in SD.SOURCES:
        path = ROOT / ("%s.xml" % source.key)
        if path.exists():
            entries.extend(SD.parse_feed(path.read_bytes(), source))
    digest = S.build(entries, seen=None, also=args.keep)
    if digest.empty:
        print("  ! nothing ranked — is the bundle empty?")
        return 1
    top = digest.story
    print("  story: %s" % top.title)
    print("  desk : %s" % (top.source.name if top.source else "?"))

    article = trim_article(top.link)
    print("  article page: %d bytes" % len(article))
    if not args.dry_run:
        (ROOT / "article.html").write_bytes(article)

    # The Persian lines the sample needs: the headlines and opening sentences of the
    # stories that could come out on top, so an offline preview reads like the real one.
    wanted = []
    for entry in [digest.story] + list(digest.also) + list(digest.ranked[1:6]):
        if entry is None:
            continue
        wanted.append(entry.title)
        lead = __import__("secwire.text", fromlist=["text"]).sentence_trim(entry.summary, 2, 520)
        if lead:
            wanted.append(lead)
            wanted.append(__import__("secwire.text", fromlist=["text"]).sentence_trim(entry.summary, 1, 260))
    wanted = list(dict.fromkeys(wanted))

    translator = Translator()                    # the same provider chain the tool uses
    translations = {}
    for index, line in enumerate(wanted, 1):
        persian = translator.to_persian(line)
        if persian:
            translations[line] = persian
        else:
            print("  ! no translation for line %d: %.60s…" % (index, line))
        time.sleep(0.4)
    print("  translations: %d of %d lines" % (len(translations), len(wanted)))
    if not args.dry_run:
        (ROOT / "translate.json").write_text(
            json.dumps(translations, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print("\n%s" % ("dry run — nothing written" if args.dry_run else "fixtures refreshed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
