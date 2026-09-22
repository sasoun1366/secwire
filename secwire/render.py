"""Turning the chosen story into the messages that go to the channel.

House style, in one place: a headline you can read at arm's length, the category
and the date as a quiet line underneath, two sentences of what happened, then the
part most security channels skip — what to do about it — and the link. Persian
first, then the same in English, then the other headlines of the day in one line
each. Nothing else, and no wall of text: a photo post's caption is capped at 1024
characters by Telegram, and long messages get cut rather than sent in three parts.
"""

from __future__ import annotations

import hashlib
import pathlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from . import jalali
from . import story as S
from . import tips
from . import text as T
from .sources import Entry
from .translate import Translator, clean_persian, persian_or_none

CAPTION_LIMIT = 1024
#: The picture for days the story has none: an advisory page rarely carries one, and
#: the channel's style is a photograph with a caption. Drawn once by tools/make_cover.py.
COVER = pathlib.Path(__file__).parent / "assets" / "cover.png"
MESSAGE_LIMIT = 4096
DEFAULT_CHANNEL = "@luyavaai"
REPO = "https://github.com/sasoun1366/secwire"


@dataclass
class Message:
    kind: str                      # "photo" or "text"
    text: str = ""
    image: str = ""
    label: str = ""                # fa / en / also / tip — for logs and the preview

    def size(self) -> int:
        return len(self.text)


@dataclass
class Post:
    messages: List[Message] = field(default_factory=list)
    story: Optional[Entry] = None
    category: str = "general"
    when: Optional[datetime] = None
    tip: Optional[int] = None

    @property
    def has_photo(self) -> bool:
        return bool(self.messages and self.messages[0].kind == "photo")

    def texts(self) -> List[str]:
        return [m.text for m in self.messages]

    def headline(self) -> str:
        if self.story:
            return self.story.title
        if self.tip is not None:
            return S.advice("general")[1]
        return "secwire"


# --------------------------------------------------------------------------- dates


def date_line_fa(when: datetime) -> str:
    return "%s %s" % (jalali.weekday_fa(when.date()), jalali.format_fa(when))


def date_line_en(when: datetime) -> str:
    return "%s, %s" % (when.strftime("%A"), jalali.format_en(when))


# --------------------------------------------------------------------------- parts


def footer(channel: str = DEFAULT_CHANNEL, with_repo: bool = True) -> str:
    line = "📡 کانال اخبار روزانهٔ امنیت شبکه: %s" % T.esc(channel)
    if with_repo:
        line += "\n<i>secwire · %s</i>" % T.esc(REPO.replace("https://", ""))
    return line


def also_block(entries: Sequence[Entry], channel: str = DEFAULT_CHANNEL) -> str:
    """The other stories of the day: a line each, no commentary."""
    if not entries:
        return ""
    fa: List[str] = ["📌 <b>امروز در یک نگاه</b>", ""]
    en: List[str] = ["📌 <b>Also today</b>", ""]
    for entry in entries:
        desk = entry.source.name if entry.source else entry.host
        fa.append("• %s — %s" % (T.link(entry.link, T.truncate(entry.title, 120)), T.esc(desk)))
        en.append("• %s — %s" % (T.link(entry.link, T.truncate(entry.title, 120)), T.esc(desk)))
    return "\n".join(fa) + "\n\n" + "\n".join(en) + "\n\n" + footer(channel)


def caption(story: Entry, category: str, when: datetime, translator: Optional[Translator],
            channel: str = DEFAULT_CHANNEL) -> str:
    """The line under the photograph: what happened, in both languages, in half a screen."""
    fa_title = persian_or_none(translator, story.title)
    cat_fa, cat_en = S.category_labels(category)
    lead = T.sentence_trim(story.summary, sentences=1, limit=260)
    lead_fa = clean_persian(persian_or_none(translator, lead) or "")

    lines = ["🛡 <b>%s</b>" % T.esc(clean_persian(fa_title) if fa_title else story.title)]
    if lead_fa:
        lines.append("")
        lines.append(T.esc(lead_fa))
    lines.append("")
    lines.append("<b>%s</b>" % T.esc(story.title))
    lines.append("")
    lines.append("🏷 %s · %s" % (T.esc(cat_fa), T.esc(date_line_fa(when))))
    desk = story.source.name if story.source else story.host
    lines.append("🌐 %s" % T.esc(desk))
    lines.append("")
    lines.append(footer(channel, with_repo=False))

    text = "\n".join(lines)
    if len(text) <= CAPTION_LIMIT:
        return text
    # Give up the Persian lead line rather than the headline: the caption has to fit.
    lean = ["🛡 <b>%s</b>" % T.esc(clean_persian(fa_title) if fa_title else story.title),
            "", "<b>%s</b>" % T.esc(story.title), "",
            "🏷 %s · %s" % (T.esc(cat_fa), T.esc(date_line_fa(when))),
            "🌐 %s" % T.esc(desk), "", footer(channel, with_repo=False)]
    return T.truncate("\n".join(lean), CAPTION_LIMIT, ellipsis="…")


def body_fa(story: Entry, category: str, when: datetime, translator: Optional[Translator],
            channel: str = DEFAULT_CHANNEL) -> str:
    cat_fa, _cat_en = S.category_labels(category)
    advice_fa, _advice_en = S.advice(category)
    title_fa = persian_or_none(translator, story.title)
    lead = T.sentence_trim(story.summary, sentences=2, limit=520)
    lead_fa = clean_persian(persian_or_none(translator, lead) or "") if lead else ""

    lines = ["🛡 <b>%s</b>" % T.esc(clean_persian(title_fa) if title_fa else story.title),
             "🏷 %s · %s" % (T.esc(cat_fa), T.esc(date_line_fa(when)))]
    if lead_fa:
        lines += ["", T.esc(lead_fa)]
    else:
        lines += ["", "⚠️ <i>ترجمهٔ ماشینی در دسترس نبود؛ متن اصلی در پیام بعدی.</i>"]
    lines += ["", "🧰 <b>چه کار کنیم</b>", T.esc(advice_fa)]
    desk = story.source.name if story.source else story.host
    lines += ["", "🔗 %s — %s" % (T.link(story.link, "ادامهٔ خبر"), T.esc(desk)),
              "", footer(channel)]
    return T.truncate("\n".join(lines), MESSAGE_LIMIT, ellipsis="…\n\n" + footer(channel))


def body_en(story: Entry, category: str, when: datetime,
            channel: str = DEFAULT_CHANNEL) -> str:
    _cat_fa, cat_en = S.category_labels(category)
    _advice_fa, advice_en = S.advice(category)
    lead = T.sentence_trim(story.summary, sentences=2, limit=520)
    lines = ["🛡 <b>%s</b>" % T.esc(story.title),
             "🏷 %s · %s" % (T.esc(cat_en), T.esc(date_line_en(when)))]
    if lead:
        lines += ["", T.esc(lead)]
    lines += ["", "🧰 <b>What to do</b>", T.esc(advice_en)]
    desk = story.source.name if story.source else story.host
    # The anchor already carries the desk's name in English, so it is not repeated.
    lines += ["", "🔗 %s" % T.link(story.link, "Read it at %s" % desk),
              "", footer(channel)]
    return T.truncate("\n".join(lines), MESSAGE_LIMIT, ellipsis="…\n\n" + footer(channel))


def tip_messages(index: int, when: datetime, translator: Optional[Translator],
                 channel: str = DEFAULT_CHANNEL) -> List[Message]:
    fa, en, why = tips.get(index)
    fa_out = persian_or_none(translator, en)
    head_fa = "💡 <b>نکتهٔ امنیتی امروز</b>"
    lines = [head_fa, "🗓 %s" % T.esc(date_line_fa(when)), "",
             T.esc(clean_persian(fa_out) if fa_out else fa),
             "", "<i>%s</i>" % T.esc(clean_persian(persian_or_none(translator, why) or "")),
             "", footer(channel)]
    fa_text = T.truncate("\n".join([l for l in lines if l is not None]), MESSAGE_LIMIT)
    en_text = "\n".join(["💡 <b>Today's security tip</b>", "🗓 %s" % T.esc(date_line_en(when)),
                         "", T.esc(en), "", "<i>%s</i>" % T.esc(why), "", footer(channel)])
    return [Message("text", fa_text.strip(), label="tip-fa"),
            Message("text", en_text.strip(), label="tip-en")]


# --------------------------------------------------------------------------- entry


def picture_for(story: Entry, cover: Optional[str] = None) -> str:
    """The story's own photograph, or the bundled cover when the page has none."""
    if story is not None and story.image:
        return story.image
    candidate = pathlib.Path(cover) if cover else COVER
    return str(candidate) if candidate and candidate.exists() else ""


def build(
    digest,
    translator: Optional[Translator] = None,
    when: Optional[datetime] = None,
    photo: bool = True,
    also: bool = True,
    channel: str = DEFAULT_CHANNEL,
    cover: Optional[str] = None,
) -> Post:
    """The day's post, ready to hand to the wire."""
    when = when or datetime.now(timezone.utc)
    if digest is None or digest.empty:
        raise ValueError("nothing to render: the digest is empty")

    story = digest.story
    messages: List[Message] = []
    image = picture_for(story, cover)
    if photo and image:
        # Telegram fetches the photograph from the article, so the tool never has to
        # store somebody else's picture to publish it.
        messages.append(
            Message("photo", caption(story, digest.category, when, translator, channel),
                    image=image, label="caption")
        )
    else:
        messages.append(
            Message("text", caption(story, digest.category, when, translator, channel),
                    label="caption")
        )
    messages.append(Message("text", body_fa(story, digest.category, when, translator, channel),
                            label="fa"))
    messages.append(Message("text", body_en(story, digest.category, when, channel), label="en"))
    if also and digest.also:
        messages.append(Message("text", also_block(digest.also, channel), label="also"))
    return Post(messages=messages, story=story, category=digest.category, when=when)


def build_tip(index: Optional[int] = None, translator: Optional[Translator] = None,
              when: Optional[datetime] = None, channel: str = DEFAULT_CHANNEL) -> Post:
    """A day with no fresh news still gets a post: a tip, chosen by the date."""
    when = when or datetime.now(timezone.utc)
    if index is None:
        seed = hashlib.sha1(when.date().isoformat().encode("utf-8")).hexdigest()
        index = int(seed[:8], 16) % tips.count()
    return Post(messages=tip_messages(index, when, translator, channel),
                category="tip", when=when, tip=index)


# --------------------------------------------------------------------------- preview


def preview_html(post: Post, title: str = "secwire — today's post") -> str:
    """A static page that looks like the channel, for the repository's docs."""
    bubbles: List[str] = []
    for message in post.messages:
        label = T.esc(message.label or message.kind)
        if message.kind == "photo":
            body = _photo_block(message.image) + "<div class=\"text\">%s</div>" % _html_text(message.text)
        else:
            body = "<div class=\"text\">%s</div>" % _html_text(message.text)
        bubbles.append(
            "<div class=\"bubble\"><div class=\"meta\">%s</div>%s</div>" % (label, body)
        )
    return _PAGE.replace("<!--bubbles-->", "\n".join(bubbles)).replace("<!--title-->", T.esc(title))


def _photo_block(image: str) -> str:
    """The picture in the preview.

    A file that is here (the bundled cover) is inlined, so the page works with no
    network at all; an article's photograph stays a URL, which is exactly how Telegram
    gets it too.
    """
    if not image:
        return ""
    if image.startswith(("http://", "https://")):
        return ('<div class="photo"><img src="%s" alt="">'
                '<span>the story&rsquo;s own photograph, fetched by Telegram</span></div>'
                % T.esc_attr(image))
    path = pathlib.Path(image)
    if path.exists() and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        import base64
        import mimetypes

        kind = mimetypes.guess_type(path.name)[0] or "image/png"
        blob = base64.b64encode(path.read_bytes()).decode("ascii")
        return ('<div class="photo"><img src="data:%s;base64,%s" alt="">'
                '<span>secwire&rsquo;s own card — used on days the story has no picture</span></div>'
                % (kind, blob))
    return '<div class="photo"><span>a photograph travels with this post</span></div>'


def _html_text(text: str) -> str:
    """Telegram HTML is already escaped by the renderer; keep the tags, wrap the lines."""
    return text.replace("\n", "<br>")


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>secwire — preview</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; padding:28px 16px 60px; background:#0e1621; color:#e9edf2;
         font:16px/1.65 -apple-system,"Segoe UI",Roboto,"Noto Naskh Arabic",Tahoma,sans-serif; }
  h1 { font-size:17px; font-weight:600; text-align:center; color:#8fa6bd; margin:0 0 22px; }
  .chat { max-width:640px; margin:0 auto; display:flex; flex-direction:column; gap:12px; }
  .bubble { background:#182533; border-radius:14px; padding:14px 16px 12px;
            box-shadow:0 1px 0 rgba(0,0,0,.25); align-self:flex-start; max-width:100%; }
  .meta { font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:#5f7488;
          margin-bottom:8px; }
  .text { white-space:normal; word-wrap:break-word; }
  .text b { color:#ffffff; }
  .text a { color:#6ab7ff; text-decoration:none; }
  .text i { color:#a9bccd; }
  .photo { position:relative; border-radius:10px; margin-bottom:12px; overflow:hidden;
           background:linear-gradient(135deg,#12314f,#1b4a6b 45%,#0d2137); }
  .photo img { display:block; width:100%; height:auto; }
  .photo span { display:block; color:#7fa8c9; font-size:12px; padding:8px 10px; }
  footer { max-width:640px; margin:26px auto 0; color:#5f7488; font-size:12px;
           text-align:center; }
</style></head><body>
<h1><!--title--></h1>
<div class="chat">
<!--bubbles-->
</div>
<footer>rendered by <code>secwire preview</code> — the real post goes out as a photograph
with this caption, then the Persian body, the English body, and the other headlines.</footer>
</body></html>
"""
