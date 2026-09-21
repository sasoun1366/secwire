"""What the channel has already said, so it does not say it again.

The file lives next to the tool's other state and is meant to survive: on GitHub
Actions it is committed back to the repository after every post, because a runner
starts each day with a clean disk and a memory of nothing.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import story as S
from .sources import Entry

DEFAULT_HOME = "~/.secwire"
KEEP_DAYS = 45
KEEP_ITEMS = 400


def home() -> pathlib.Path:
    path = pathlib.Path(os.environ.get("SECWIRE_HOME") or DEFAULT_HOME).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_file(root: Optional[pathlib.Path] = None) -> pathlib.Path:
    return (root or home()) / "seen.json"


class Seen:
    """The list of stories this channel has published, newest last."""

    def __init__(self, path: Optional[pathlib.Path] = None, rows: Optional[List[Dict]] = None):
        self.path = path
        self.rows: List[Dict] = rows if rows is not None else []
        self._ids = {row.get("id") for row in self.rows}
        self._links = {row.get("link") for row in self.rows}
        self._titles = {row.get("title", "").lower() for row in self.rows}

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, root: Optional[pathlib.Path] = None) -> "Seen":
        path = state_file(root)
        if not path.exists():
            return cls(path=path, rows=[])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            # A corrupt memory is not a reason to skip a day's post: start it again.
            return cls(path=path, rows=[])
        rows = data.get("entries") if isinstance(data, dict) else data
        return cls(path=path, rows=list(rows or []))

    # ------------------------------------------------------------------ asking
    def knows(self, entry: Entry) -> bool:
        if S.identity(entry) in self._ids:
            return True
        if (entry.link or "") in self._links:
            return True
        return (entry.title or "").lower() in self._titles

    def __len__(self) -> int:
        return len(self.rows)

    def latest(self) -> Optional[Dict]:
        return self.rows[-1] if self.rows else None

    def recent(self, entries: int = 10) -> List[Dict]:
        return self.rows[-entries:]

    # ------------------------------------------------------------------ writing
    def remember(self, entry: Entry, kind: str = "story") -> None:
        self.rows.append(
            {
                "id": S.identity(entry),
                "title": entry.title,
                "link": entry.link,
                "source": entry.source.key if entry.source else "",
                "kind": kind,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        self._ids.add(S.identity(entry))
        self._links.add(entry.link)
        self._titles.add((entry.title or "").lower())

    def prune(self, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        before = len(self.rows)
        keep: List[Dict] = []
        for row in self.rows:
            try:
                when = datetime.fromisoformat(row.get("at", "").replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            except ValueError:
                when = now
            if now - when <= timedelta(days=KEEP_DAYS):
                keep.append(row)
        self.rows = keep[-KEEP_ITEMS:]
        self._ids = {row.get("id") for row in self.rows}
        self._links = {row.get("link") for row in self.rows}
        self._titles = {row.get("title", "").lower() for row in self.rows}
        return before - len(self.rows)

    def save(self) -> pathlib.Path:
        path = self.path or state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps({"version": 1, "entries": self.rows},
                          ensure_ascii=False, indent=1, sort_keys=False) + "\n"
        handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".seen-", suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(blob)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
        return path
