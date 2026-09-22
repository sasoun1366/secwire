"""secwire — one network-security story a day, posted to a Telegram channel.

The tool reads public security feeds, picks the story of the day, and renders a
bilingual post (Persian + English) with the article's own photograph. It is meant
to run unattended on a schedule, so every step has a fallback: no fresh story
means a hygiene tip, no photograph means a text post with a preview, no
translation means the English text stands alone. The channel never goes quiet.

Zero dependencies, Python 3.9+.
"""

__version__ = "0.1.1"

USER_AGENT = "secwire/%s (+https://github.com/sasoun1366/secwire)" % __version__
