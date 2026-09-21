"""The wire to Telegram: two methods, a dry run, and a fallback for every failure.

The bot has one job here — post into a channel it administers. Everything that can
go wrong on a bad morning has an answer: a photograph Telegram will not fetch means
the bundled cover is uploaded instead, and if even that fails the caption goes as a
message on its own; a 429 is waited out; a message longer than Telegram accepts is
cut at a line boundary. A run is never left half-done silently.
"""

from __future__ import annotations

import json
import mimetypes
import pathlib
import time
import urllib.error
import urllib.request
import uuid
from typing import Dict, List, Optional, Tuple

from . import USER_AGENT
from .render import MESSAGE_LIMIT, Message, Post

API_BASE = "https://api.telegram.org"
ATTEMPTS = 3
BACKOFF = 2.0


class TelegramError(RuntimeError):
    """Telegram answered with an error. The text is the API's own description."""


def _multipart(fields: Dict[str, str], files: Dict[str, Tuple[str, bytes]]) -> Tuple[bytes, str]:
    """A multipart/form-data body, built by hand: stdlib only, no requests."""
    boundary = "----secwire%s" % uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                % (boundary, name, value)).encode("utf-8")
    for name, (filename, blob) in files.items():
        kind = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                "Content-Type: %s\r\n\r\n" % (boundary, name, filename, kind)).encode("utf-8")
        out += blob
        out += b"\r\n"
    out += ("--%s--\r\n" % boundary).encode("utf-8")
    return bytes(out), boundary


class Transport:
    """Where calls go. Tests use a recorder; production uses HTTPS."""

    def call(self, method: str, payload: Dict, files: Optional[Dict] = None) -> Dict:
        raise NotImplementedError                             # pragma: no cover - interface

    def describe(self) -> str:
        return type(self).__name__


class HttpTransport(Transport):
    def __init__(self, token: str, api_base: str = API_BASE, timeout: int = 40):
        if not token:
            raise TelegramError("no bot token: set SECWIRE_TELEGRAM_TOKEN or TELEGRAM_BOT_TOKEN")
        self.token = token
        self.api_base = (api_base or API_BASE).rstrip("/")
        self.timeout = timeout

    def describe(self) -> str:
        return "https → %s (token …%s)" % (self.api_base, self.token[-4:])

    def call(self, method: str, payload: Dict, files: Optional[Dict] = None) -> Dict:
        url = "%s/bot%s/%s" % (self.api_base, self.token, method)
        if files:
            body, boundary = _multipart({k: str(v) for k, v in payload.items()}, files)
            headers = {"Content-Type": "multipart/form-data; boundary=%s" % boundary,
                       "User-Agent": USER_AGENT}
        else:
            body = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        last: Optional[Exception] = None
        for attempt in range(1, ATTEMPTS + 1):
            request = urllib.request.Request(url, data=body, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")
                try:
                    described = json.loads(detail).get("description", detail)
                except ValueError:
                    described = detail[:200]
                if exc.code == 429:                           # rate limited: wait and retry
                    last = TelegramError("429 %s" % described)
                    time.sleep(BACKOFF * attempt)
                    continue
                raise TelegramError("%s: %s" % (method, described)) from None
            except Exception as exc:                          # noqa: BLE001 — network weather
                last = exc
                time.sleep(BACKOFF * attempt)
        raise TelegramError("%s failed after %d attempts: %s" % (method, ATTEMPTS, last))


class RecordingTransport(Transport):
    """A dry run that keeps everything: the calls, their order, their payloads."""

    def __init__(self, echo: bool = False):
        self.calls: List[Dict] = []
        self.echo = echo

    def describe(self) -> str:
        return "dry run (nothing is sent)"

    def call(self, method: str, payload: Dict, files: Optional[Dict] = None) -> Dict:
        record = {"method": method, "payload": payload}
        if files:
            record["files"] = {name: len(blob) for name, (_f, blob) in files.items()}
        self.calls.append(record)
        if self.echo:
            print("   → %s" % method)
        return {"ok": True, "result": {"message_id": len(self.calls), "dry_run": True}}


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> List[str]:
    """Split on a line boundary, so a cut never lands in the middle of a sentence."""
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    current: List[str] = []
    size = 0
    for line in text.splitlines():
        addition = len(line) + 1
        if size + addition > limit and current:
            parts.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += addition
    if current:
        parts.append("\n".join(current))
    return parts


def send_message(transport: Transport, chat_id, text: str, label: str = "",
                 preview: bool = False) -> List[Dict]:
    out: List[Dict] = []
    for chunk in split_text(text):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": not preview,
            "disable_notification": False,
        }
        if label:
            payload["secwire_label"] = label        # ignored by Telegram, read in a dry run
        out.append(transport.call("sendMessage", payload))
    return out


def photo_payload(photo: str):
    """A URL is handed to Telegram as a string; a local file is uploaded as bytes."""
    if photo.startswith(("http://", "https://")):
        return photo, None
    path = pathlib.Path(photo).expanduser()
    if not path.exists():
        raise TelegramError("no such file: %s" % path)
    name = path.name or "photo.png"
    return None, {name: (name, path.read_bytes())}


def send_photo(transport: Transport, chat_id, photo: str, caption: str) -> Dict:
    reference, files = photo_payload(photo)
    payload = {
        "chat_id": chat_id,
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }
    if reference:
        payload["photo"] = reference
        return transport.call("sendPhoto", payload)
    image = {"photo": next(iter(files.values()))}
    return transport.call("sendPhoto", payload, files=image)


def deliver(transport: Transport, chat_id, post: Post, dry_run: bool = False) -> Dict:
    """Post the whole thing, in order, with the fallbacks Telegram makes necessary."""
    sent: List[str] = []
    for message in post.messages:
        label = message.label or message.kind
        if message.kind == "photo" and message.image:
            try:
                send_photo(transport, chat_id, message.image, message.text)
                sent.append("photo:" + ("url" if message.image.startswith("http") else "upload"))
                continue
            except TelegramError as exc:
                # The article's picture is not always something Telegram will fetch, and
                # the bundled cover may be missing from a slim checkout. The caption is
                # written to stand on its own, so send it as a message.
                print("   photo refused (%s) — sending the caption as a message" % exc)
        send_message(transport, chat_id, message.text, label=label)
        sent.append(label)
    return {"ok": True, "sent": sent, "messages": len(post.messages)}


def whoami(transport: Transport) -> Dict:
    return transport.call("getMe", {})


def chat_check(transport: Transport, chat_id) -> Dict:
    return transport.call("getChat", {"chat_id": chat_id})


def chat_id_from(value) -> object:
    """A channel id arrives as -100…, an @name, or an id typed with spaces."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("@") or text.lstrip("-").isdigit():
        return int(text) if text.lstrip("-").isdigit() else text
    return text
