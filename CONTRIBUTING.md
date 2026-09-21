# Contributing

Thanks for looking. This is a small tool with a narrow job, and the fastest way to
help is to keep it narrow.

## The rules that keep it small

* **Zero required dependencies.** The standard library, Python 3.9+, and nothing
  else. Pillow is allowed only inside `tools/`, which a daily post never runs.
* **The tests never touch the network.** Everything they read is in
  `secwire/fixtures/`. If your change needs a new page to test against, refresh the
  bundle with `python3 tools/make_fixtures.py` and commit the diff.
* **The feed decides the content.** The post is the story's own headline, its own
  opening lines and a link. The only text this project adds is standing advice and
  the channel furniture — no rewriting a story to make it sound better.
* **Every failure has a fallback.** A dead feed, a missing photograph, an endpoint
  that answers in English: the post still goes out, and the run log says what
  happened.
* **Nothing secret in the repository.** The bot token and the channel id come from
  the environment, and the state directory is ignored for local runs.

## Before you send a patch

```console
$ pip install -e ".[dev]"
$ pytest -q
$ secwire sample           # read the post you just changed
$ secwire doctor --offline
```

A change to the wording of a post should show up in `docs/preview.html` too: run
`secwire preview --out docs/preview.html` and commit the result.

## Adding a feed

1. add a `Source(...)` line to `SOURCES` in `secwire/sources.py`, with a weight and a
   one-line reason it is on the desk
2. `python3 tools/make_fixtures.py` to freeze a few of its items
3. `secwire sources` and `secwire digest --offline` to see it in the ranking

If the feed needs special parsing, that belongs in `parse_feed`, not in the new line.
