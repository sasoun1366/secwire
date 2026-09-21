"""Small shared things for the tests: no network, no clock, no surprises."""

from __future__ import annotations

import os
import stat
import pathlib

import pytest

from secwire import text as T

FROZEN_DAY = "2026-09-21"


def assert_private(path: pathlib.Path) -> None:
    """0600 where the platform has POSIX modes; Windows keeps its own ACLs."""
    if os.name != "posix":
        pytest.skip("file modes are a POSIX notion")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, "expected 0600, found %o" % mode


def plain(html: str) -> str:
    """Telegram HTML as a person reads it, for assertions about what the text says."""
    return T.strip_html(html.replace("<br>", "\n"))
