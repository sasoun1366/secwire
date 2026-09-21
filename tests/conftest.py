"""Fixtures for the whole suite: the bundled wire, a frozen clock, a throwaway home."""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from secwire import fixtures as FX                                    # noqa: E402
from secwire import story as S                                        # noqa: E402

#: The fixtures were frozen on this day, so a test that asks for "the story of the
#: day" gets the same story the sample and the docs show.
FROZEN = datetime(2026, 9, 21, 6, 30, tzinfo=timezone.utc)


@pytest.fixture
def wire():
    """Every entry in the bundled wire — what the feeds looked like at freeze time."""
    entries, errors = FX.entries()
    assert not errors, errors
    assert entries
    return entries


@pytest.fixture
def ranked(wire):
    return S.rank(wire, now=FROZEN, limit=12)


@pytest.fixture
def digest(wire):
    return S.build(wire, now=FROZEN, also=3)


@pytest.fixture
def translator():
    """A translator whose every answer comes out of the fixtures, not the internet."""
    from secwire.translate import Translator

    return Translator(transport=FX.FixtureOpener())


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A private state directory, so a test never touches the real one."""
    root = tmp_path / "secwire-home"
    root.mkdir()
    monkeypatch.setenv("SECWIRE_HOME", str(root))
    return root
