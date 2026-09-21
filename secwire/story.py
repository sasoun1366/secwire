"""Choosing the story of the day, and knowing it has not been posted before.

Ranking is deliberately explainable: freshness, how much the story is *about* the
network, how much it is about defending rather than selling, and the desk that ran
it. Every story carries its score with it, so `secwire digest` can show the reader
why one story beat another instead of asking them to trust a number.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .sources import Entry, hours_ago

# --------------------------------------------------------------------------- words

#: Signals that a story is about an attack, a flaw, or a patch — the things this
#: channel exists for.
RELEVANT = (
    ("zero-day", 26), ("zero day", 26), ("actively exploited", 24), ("exploited in the wild", 24),
    ("ransomware", 22), ("data breach", 20), ("breach", 14), ("vulnerability", 16),
    ("cve-", 18), ("patch", 12), ("security update", 12), ("flaw", 14), ("exploit", 16),
    ("malware", 16), ("backdoor", 16), ("botnet", 14), ("phishing", 13), ("credential", 12),
    ("hacked", 14), ("hijack", 12), ("spyware", 14), ("supply chain", 16), ("stolen", 12),
    ("firmware", 14), ("router", 14), ("vpn", 13), ("firewall", 12), ("dns", 12), ("tls", 10),
    ("ddos", 12), ("cisa", 14), ("kev catalog", 16), ("two-factor", 10), ("authentication", 10),
    ("password", 10), ("leaked", 12), ("extortion", 12), ("infostealer", 16), ("cryptominer", 10),
    ("active directory", 14), ("exchange server", 14), ("esxi", 12), ("citrix", 12),
    ("fortinet", 12), ("cisco", 12), ("mikrotik", 16), ("ivanti", 12), ("sonicwall", 12),
    ("microsoft", 10), ("linux", 9), ("windows server", 10), ("openssh", 12), ("apache", 10),
    ("nation-state", 12), ("apt", 6), ("cyberattack", 14), ("incident", 10),
)

#: Signals that this is commerce wearing a security hat.
NOISE = (
    ("webinar", -30), ("register now", -30), ("podcast", -14), ("sponsored", -40),
    ("whitepaper", -30), ("award", -22), ("appoints", -26), ("appointed", -26),
    ("names new", -26), ("partnership", -14), ("acquires", -18), ("acquisition", -18),
    ("funding round", -24), ("raises $", -24), ("series a", -24), ("series b", -24),
    ("quarterly results", -30), ("earnings", -30), ("hiring", -24), ("survey finds", -20),
    ("report reveals", -8), ("summit", -20), ("conference", -22), ("product launch", -26),
    ("unveils", -22), ("at rsa", -16), ("black hat", -10), ("how to watch", -30),
    ("best ", -8), ("top 10", -12), ("gift guide", -40), ("deal", -14),
)

#: What the story is about — drives the advice line at the bottom of the post.
CATEGORIES: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    ("vulnerability", "آسیب‌پذیری و وصله", "Vulnerability and patch",
     ("cve-", "cve", "vulnerability", "flaw", "zero-day", "patch", "security update",
      "actively exploited", "exploited in the wild", "exploitation", "kev",
      "advisory", "hotfix")),
    ("ransomware", "باج‌افزار", "Ransomware and extortion",
     ("ransomware", "extortion", "double extortion", "lockbit", "ransom")),
    ("breach", "نشت داده", "Data breach",
     ("breach", "leaked", "exposed database", "stolen data", "data leak", "records")),
    ("malware", "بدافزار", "Malware and implants",
     ("malware", "backdoor", "botnet", "infostealer", "trojan", "rat ", "spyware",
      "loader", "stealer", "cryptominer")),
    ("phishing", "فیشینگ و مهندسی اجتماعی", "Phishing and social engineering",
     ("phishing", "smishing", "credential harvesting", "social engineering", "vishing",
      "scam", "fake login", "impersonat")),
    ("network", "زیرساخت و تجهیزات شبکه", "Network infrastructure and devices",
     ("router", "firewall", "vpn", "mikrotik", "cisco", "fortinet", "ivanti", "sonicwall",
      "citrix", "dns", "bgp", "tls", "esxi", "firmware", "switch", "nas ", "openssh")),
    ("policy", "سیاست و مقررات", "Policy and regulation",
     ("regulation", "law", "court", "sanction", "directive", "government", "policy",
      "privacy shield", "gdpr", "legislation")),
    ("general", "امنیت شبکه", "Network security", ()),
)

#: Advice per category. Written as standing guidance, not as a claim about the
#: story: secwire has not seen the reader's network, so it says what to check, not
#: what will happen to them.
ADVICE: Dict[str, Tuple[str, str]] = {
    "vulnerability": (
        "این دسته معمولاً با یک وصله بسته می‌شود. اگر آن سرویس روی لبهٔ شبکهٔ شماست، "
        "امروز به‌روزرسانی‌اش کنید — نه آخر هفته.",
        "This class of bug is closed by a patch. If that service is on your edge, "
        "update it today rather than at the weekend.",
    ),
    "ransomware": (
        "باج‌افزار روی مسیرهای ورودیِ باز سوار می‌شود: RDP بی‌نگهبان، VPN وصله‌نشده، "
        "پشتیبانِ وصل به شبکه. امشب یکی از این سه را ببند، و مطمئن شو پشتیبان آفلاین است.",
        "Ransomware rides in through open doors: unprotected RDP, an unpatched VPN, a "
        "backup server that is reachable. Close one of those tonight, and confirm the "
        "backup is offline.",
    ),
    "breach": (
        "پس از هر نشت، دو کار مهم است: چرخاندن رمزها و بررسی ورودهای ناموفق. اگر "
        "حساب‌ها دو مرحله‌ای دارند، امروز جای خوبی برای چک‌کردنشان است.",
        "After a breach, two things matter: rotate the passwords and read the failed "
        "logins. If the accounts have two-step verification, today is a good day to check.",
    ),
    "malware": (
        "بدافزارِ امروز دنبال یک اجرای اشتباه است. روی میز کار، اجرای فایل از پوشهٔ "
        "دانلود و ماکروی آفیس را ببند؛ روی شبکه، خروجیِ غیرمنتظره را محدود کن.",
        "Today's malware needs one mistake to run. Ban executing files from the download "
        "folder and switch macros off; on the network, restrict unexpected outbound traffic.",
    ),
    "phishing": (
        "قاعدهٔ سادهٔ فیشینگ: لینکِ ایمیل را باز نکن، خودت آدرس را تایپ کن. برای "
        "کارمندان هم فیلترِ فنی (DMARC، MFA) از آموزش مؤثرتر است.",
        "The simple anti-phishing rule: do not open the link, type the address yourself. "
        "For staff, the technical filter (DMARC, MFA) beats the training slide.",
    ),
    "network": (
        "تجهیزات لبه بیشتر از هر سروری در شبکه دوام می‌آورند و کمتر به‌روز می‌شوند. "
        "امروز فهرست فریمورِ دستگاه‌های لبه را با نسخهٔ روز سازنده مقایسه کن.",
        "Edge devices outlive every other box on the network and get patched last. Today, "
        "compare the firmware list against the vendor's current release.",
    ),
    "policy": (
        "مقررات به‌تنهایی کسی را امن نمی‌کند، ولی رهنمودها اغلب کاری که باید بکنی را "
        "دقیق گفته‌اند. متن اصلی را بخوان، نه تیتر آن را.",
        "A regulation alone secures nobody, but guidance usually says precisely what to do. "
        "Read the primary text rather than the headline about it.",
    ),
    "general": (
        "امروز چند دقیقه وقت بگذار و لاگ ورودهای ناموفق را نگاه کن؛ همان چیزی که "
        "هیچ‌کس نمی‌خواند، معمولاً اول از همه خبر بد را می‌گوید.",
        "Spend a few minutes reading the failed-login log today; the thing nobody reads is "
        "usually the first to say bad news.",
    ),
}


def classify(entry: Entry) -> str:
    haystack = ("%s %s" % (entry.title, entry.summary)).lower()
    best, best_hits = "general", 0
    for key, _fa, _en, needles in CATEGORIES:
        hits = sum(1 for needle in needles if needle in haystack)
        if hits > best_hits:
            best, best_hits = key, hits
    return best


def category_labels(key: str) -> Tuple[str, str]:
    for k, fa, en, _needles in CATEGORIES:
        if k == key:
            return fa, en
    return "امنیت شبکه", "Network security"


def advice(key: str) -> Tuple[str, str]:
    return ADVICE.get(key, ADVICE["general"])


def relevance(entry: Entry) -> float:
    haystack = ("%s %s" % (entry.title, entry.summary)).lower()
    score = 0.0
    for needle, weight in RELEVANT:
        if needle in haystack:
            score += weight
    # A hit in the headline counts for more than one buried in the summary.
    title = entry.title.lower()
    for needle, weight in RELEVANT:
        if needle in title:
            score += weight * 0.5
    for needle, weight in NOISE:
        if needle in haystack:
            score += weight
    return score


def score(entry: Entry, now: Optional[datetime] = None) -> Tuple[float, List[str]]:
    """A score a reader could argue with, plus the reasons that produced it."""
    reasons: List[str] = []
    total = 0.0

    if entry.source:
        total += entry.source.weight * 0.8
        reasons.append("desk %s +%.1f" % (entry.source.key, entry.source.weight * 0.8))

    rel = relevance(entry)
    total += rel
    reasons.append("relevance +%.1f" % rel)

    age = hours_ago(entry, now)
    if age is None:
        reasons.append("no date (neutral)")
    else:
        # 24 hours old costs about the weight of a good headline.
        penalty = min(age, 120.0) / 5.0
        total -= penalty
        reasons.append("%.1f h old -%.1f" % (age, penalty))

    if len(entry.summary) < 60:
        total -= 6
        reasons.append("thin summary -6.0")
    if entry.image:
        total += 3
        reasons.append("has a picture +3.0")
    return total, reasons


def rank(entries: Iterable[Entry], now: Optional[datetime] = None,
         seen=None, limit: int = 10) -> List[Entry]:
    """Best first, already-posted stories left out."""
    now = now or datetime.now(timezone.utc)
    fresh: List[Entry] = []
    for entry in entries:
        if seen is not None and seen.knows(entry):
            continue
        total, reasons = score(entry, now)
        entry.score, entry.why = total, "; ".join(reasons)
        fresh.append(entry)
    fresh.sort(key=lambda e: (-e.score, e.title))
    return fresh[:limit]


def identity(entry: Entry) -> str:
    """A stable id for "this story" that survives a feed changing its link tracking."""
    url = re.sub(r"[?#].*$", "", (entry.link or "").lower()).replace("www.", "")
    basis = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", (entry.title or "").lower()).strip()
    basis = " ".join(basis.split()[:12])
    return hashlib.sha1(("%s|%s" % (basis, url)).encode("utf-8")).hexdigest()[:16]


_STOPWORDS = frozenset(
    "the a an and or of to in on for with from by at is are was were be been as it its "
    "this that these those new how what why you your their they them he she his her "
    "security cyber attack attacks report says said could would may might more most "
    "after before over under than then into out up down off again".split()
)


def _words(title: str):
    return {w for w in re.findall(r"[a-z0-9\-]{3,}", (title or "").lower())
            if w not in _STOPWORDS}


def same_story(a: Entry, b: Entry) -> bool:
    """Two desks often cover one story; the channel should not post it twice."""
    if identity(a) == identity(b):
        return True
    wa, wb = _words(a.title), _words(b.title)
    if not wa or not wb:
        return False
    # Share of the shorter headline's words that also appear in the other one: a
    # rewrite adds words, it rarely drops the nouns that make the story what it is.
    overlap = len(wa & wb) / float(min(len(wa), len(wb)))
    named = wa & wb & {"cve", "ransomware", "breach", "vulnerability", "phishing",
                       "malware", "exploit", "patch", "botnet", "backdoor", "leak"}
    return overlap >= 0.75 or (overlap >= 0.5 and len(named) >= 2)


@dataclass
class Digest:
    """The story of the day, plus the other headlines worth a line each."""

    story: Optional[Entry] = None
    also: List[Entry] = field(default_factory=list)
    ranked: List[Entry] = field(default_factory=list)
    category: str = "general"

    @property
    def empty(self) -> bool:
        return self.story is None


def build(entries: Sequence[Entry], now: Optional[datetime] = None, seen=None,
          also: int = 3) -> Digest:
    """Pick today's story and the runners-up that are *different* stories."""
    ranked = rank(entries, now=now, seen=seen, limit=max(10, also + 6))
    if not ranked:
        return Digest()
    story = ranked[0]
    rest: List[Entry] = []
    for candidate in ranked[1:]:
        if len(rest) >= also:
            break
        if candidate.source and story.source and candidate.source.key == story.source.key:
            # One desk, one line: the second item from the same place is usually a
            # variation of the first, and this list is meant to look hand-picked.
            continue
        if any(same_story(candidate, chosen) for chosen in [story] + rest):
            continue
        rest.append(candidate)
    return Digest(story=story, also=rest, ranked=ranked, category=classify(story))
