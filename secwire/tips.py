"""The fallback desk: a hygiene tip for the days the wire is quiet.

Two things can go wrong with a daily channel: it goes silent, or it posts filler.
A tip is not filler — it is the part of security work nobody schedules, written to
be read in thirty seconds and acted on today. There are enough of them here for a
month of quiet days, in both languages.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional, Tuple

#: (Persian, English, the one-line reason to do it)
TIPS: Tuple[Tuple[str, str, str], ...] = (
    ("پشتیبان‌گیری‌ات را یک بار *بازیابی* کن، نه فقط بگیر. پشتیبانی که تست نشده باشد "
     "پشتیبان نیست، امید است.",
     "Restore a backup rather than only taking one. An untested backup is not a backup, "
     "it is a hope.",
     "the day you need it is the day you find out"),
    ("فهرست دستگاه‌های لبه‌ات را بنویس: روتر، فایروال، VPN. بیشترین حفره همیشه "
     "همان‌جاست که کسی به‌روزش نمی‌کند.",
     "Write down your edge devices: router, firewall, VPN. The gap is always where "
     "nobody remembers to patch.",
     "edge boxes are internet-facing by definition"),
    ("ورودهای ناموفق را با دستور ساده ببین: `lastb` روی لینوکس، Event ID 4625 روی "
     "ویندوز. الگوی تکرار مهم‌تر از یک شکست است.",
     "Read the failed logins: `lastb` on Linux, event ID 4625 on Windows. The pattern "
     "matters more than the single failure.",
     "credential stuffing shows up here first"),
    ("روی حساب‌های مهم دو مرحله‌ای بگذار — و اگر روی پیامک است، برنامهٔ TOTP را "
     "جایگزین کن.",
     "Turn on two-step verification for the accounts that matter — and if it is by SMS, "
     "move to a TOTP app.",
     "SMS codes can be taken with your phone number"),
    ("رمزها را در مرورگر ذخیره نکن برای حساب‌هایی که پول جابه‌جا می‌کنند؛ برای آن‌ها "
     "یک مدیر رمز جدا بگذار.",
     "Stop saving the passwords that move money in the browser; keep those in a "
     "separate password manager.",
     "a synced password store is a single point of failure"),
    ("مدیر رمز اصلی‌ات را جایی روی کاغذ در گاوصندوق بگذار. فراموش‌کردن آن، رایج‌ترین "
     "راه از دست دادن همه‌چیز است.",
     "Keep the master password of your password manager on paper, in a safe. Forgetting "
     "it is the most common way to lose everything.",
     "recovery beats secrecy on the master key"),
    ("پورت‌های باز روی روتر را بشمار و هر کدام را که لازم نیست ببند؛ هر پورت باز یک "
     "در است.",
     "Count the open ports on your router and close the ones you do not use; every open "
     "port is a door.",
     "attack surface is a choice"),
    ("مدیریت از راه دور روتر را فقط از داخل شبکه باز بگذار. پنل مدیریت روی اینترنت، "
     "دعوت‌نامه است.",
     "Expose router administration only from inside the network. An admin panel on the "
     "internet is an invitation.",
     "management interfaces are logged into, not scanned, by attackers"),
    ("برای Wi-Fi میهمان یک شبکهٔ جدا بساز. دسترسی مهمان به پرینتر و NAS لازم نیست.",
     "Put guests on a separate Wi-Fi network. Guests do not need your printer or your NAS.",
     "one flat network turns one device into all of them"),
    ("DNS را روی سروری بگذار که لاگ دارد؛ نگاه‌کردن به کوئری‌های عجیب، ارزان‌ترین "
     "سیستم تشخیص نفوذ است.",
     "Point DNS at a server that keeps logs; reading odd lookups is the cheapest "
     "intrusion detection you will ever run.",
     "DNS is the first thing malware uses"),
    ("فایل اجرایی از پوشهٔ دانلود را با یک قاعده ببند. بیشتر بدافزارها همان‌جا "
     "اجرا می‌شوند.",
     "Block executables from running out of the download folder with one rule. That is "
     "where most malware runs.",
     "the download folder is the front door"),
    ("ماکروی آفیس را برای فایل‌های رسیده از اینترنت خاموش کن؛ به‌جای آموزش دادن، "
     "مسیر را ببند.",
     "Switch off Office macros for files that arrived from the internet; closing the "
     "path beats training people about it.",
     "macros are still a working delivery route"),
    ("رمز مدیر را با کارهای روزمره قاطی نکن: برای وب‌گردی حساب جدا داشته باش.",
     "Do not browse the web as the administrator: keep a separate account for it.",
     "browser bugs stop being domain admin bugs"),
    ("به‌روزرسانی خودکار را روشن کن و بگذار شب اجرا شود؛ وصله‌ای که نصب نشود، "
     "نوشته‌نشده است.",
     "Turn on automatic updates and let them run at night; an uninstalled patch may as "
     "well be an unwritten one.",
     "the lag between patch and exploit is now days"),
    ("کارت شبکه/دستگاه ناشناس در شبکهٔ خودت را پیدا کن: یک اسکن آرام و مقایسه با "
     "فهرست دارایی‌ها.",
     "Look for the device on your network you cannot name: one quiet scan compared "
     "against your asset list.",
     "unknown devices are the finding nobody logs"),
    ("برای همهٔ حساب‌های سرویس ایمیلی، SPF و DKIM و DMARC را تنظیم کن؛ بدون آن‌ها "
     "نام دامنه‌ات قابل جعل است.",
     "Set SPF, DKIM and DMARC for every domain that sends mail; without them your name "
     "can be forged.",
     "your own domain is the most convincing phish"),
    ("فایل پیکربندی روتر را بعد از هر تغییر ذخیره کن و نسخه‌اش را نگه دار؛ بازگشت "
     "سریع نصف کار است.",
     "Save the router configuration after every change and keep the versions; a fast "
     "rollback is half of incident response.",
     "you will want yesterday's config"),
    ("لاگ را جایی بفرست که مهاجم به آن دسترسی ندارد. لاگ روی خودِ دستگاه، بعد از "
     "نفوذ بی‌فایده است.",
     "Ship logs somewhere the attacker cannot reach. Logs on the compromised box are "
     "useless after the fact.",
     "the first thing an intruder does is clean up"),
    ("چند حساب خدماتی بی‌استفاده را ببند؛ حساب‌های قدیمی همان‌هایی هستند که کسی "
     "رمزشان را عوض نمی‌کند.",
     "Close the unused service accounts; the old ones are exactly the ones nobody "
     "rotates.",
     "unused accounts are unmonitored access"),
    ("کلید SSH را جای رمز بگذار و رمز ورود مستقیم روت را خاموش کن.",
     "Use SSH keys instead of passwords, and switch off direct root login.",
     "automated scanners only try passwords"),
    ("پورت ۳۳۸۹ را از اینترنت ببند. اگر کسی بیرون باید وصل شود، از VPN بیاید.",
     "Close port 3389 to the internet. If somebody outside needs in, they come through "
     "the VPN.",
     "exposed RDP is the most-used ransomware door"),
    ("فهرست نرم‌افزارهای نصب‌شده روی سرورها را یک بار بنویس؛ چیزی که نامش را ندانی، "
     "به‌روزش هم نمی‌کنی.",
     "Write down the software installed on your servers once; you cannot patch what you "
     "cannot name.",
     "inventory is the start of patching"),
    ("MFA را برای دسترسی مدیریتی اجباری کن، حتی داخل شبکه. مهاجمی که وارد شده، "
     "کارمند دورکار نیست.",
     "Require MFA for administrative access, even from inside. An intruder who is in is "
     "not a remote employee.",
     "the internal network is not a trust boundary"),
    ("برای هر دستگاه لبه یک حساب مدیریت جدا با نام غیر `admin` بساز و رمزش را "
     "جایی ثبت کن.",
     "Give every edge device its own admin account, with a name that is not `admin`, "
     "and record the password.",
     "default usernames are half of the credential"),
    ("یک بار سناریوی «امروز باج‌افزار می‌گیریم» را روی کاغذ بازی کن: چه کسی چه کاری "
     "می‌کند؟ سکوت در آن جلسه، خودش یک یافته است.",
     "Play the 'we get ransomware today' scenario on paper once: who does what? Silence "
     "in that meeting is itself a finding.",
     "an untested plan is a plan to improvise"),
    ("رمز وای‌فای را روی برچسب پشت روتر نگه ندار که با عکس گرفتن از راه دور خوانده "
     "شود.",
     "Stop keeping the Wi-Fi password on the sticker on the router, where a photograph "
     "from across the room reads it.",
     "physical exposure is still exposure"),
    ("برای ایمیل کاری، قالب «پاسخ به این پیام» را در پیام‌های حساس کنار بگذار: از "
     "شمارهٔ خودت تماس بگیر، نه از شماره‌ای که در پیام آمده.",
     "For money or access requests, drop reply-to-this-message: call the number you "
     "already have, not the one in the message.",
     "business email compromise is a conversation, not a bug"),
    ("سرور یا سرویسی که کسی مسئولش نیست را پیدا کن؛ دارایی بی‌مالک، دارایی وصله‌نشده "
     "است.",
     "Find the server nobody owns; an unowned asset is an unpatched asset.",
     "ownership is a security control"),
    ("امروز یک رمز را عوض کن — همان که همه‌جا استفاده کرده‌ای. یکی کافی است برای "
     "شروع.",
     "Change one password today — the one you have used everywhere. One is enough to "
     "start.",
     "reuse turns one breach into every breach"),
    ("گواهی TLS را برای ۳۰ روز آینده چک کن؛ انقضای گواهی، خطای انسانی است نه حمله — "
     "ولی همان‌قدر گران.",
     "Check the TLS certificates for the next 30 days; an expiry is human error rather "
     "than an attack, and it costs just as much.",
     "expiry is the outage you can schedule"),
)


def pick(index: int = None, salt: str = "") -> Tuple[str, str]:
    """A tip that does not repeat itself day after day."""
    if index is None:
        digest = hashlib.sha1(("%s-%s" % (salt, _today())).encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(TIPS)
    fa, en, _why = TIPS[index % len(TIPS)]
    return fa, en


def get(index: int) -> Tuple[str, str, str]:
    return TIPS[index % len(TIPS)]


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def count() -> int:
    return len(TIPS)


def as_rows() -> List[Tuple[int, str]]:
    return [(i, en.split(".")[0]) for i, (_fa, en, _why) in enumerate(TIPS)]


def why(index: int) -> str:
    return TIPS[index % len(TIPS)][2]


def title_fa(index: int = None) -> str:
    return "نکتهٔ امنیتی امروز"


def title_en(index: int = None) -> str:
    return "Today's security tip"
