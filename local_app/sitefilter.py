"""Site filter: refuses adult and suspicious sites before anything is downloaded.

Pure Python, no dependencies. server.py calls check_download() for every request and also checks the page
that yt-dlp resolves, so a video that lives on a neutral CDN but belongs to an adult page is still refused.

No list can know every site. This is built from three layers:
  1. a list of well-known adult domains (plus the user's own list, blocked_sites.txt)
  2. keywords in the site name / the first words of the path
  3. generic signs of an unsafe link (raw IP addresses, local network, user@host tricks, punycode, scam TLDs)
The user's allowed_sites.txt switches layers 2 and 3 off for trusted domains (layer 1 and user@host tricks stay).
"""
import ipaddress
import re
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import unquote, urlparse

ADULT_MESSAGE = "Blocked: this site has adult content, and downloads from it are not allowed."


class Blocked(Exception):
    """Raised when a download is refused. str(e) is the message shown to the user."""


# ---------------------------------------------------------------- 1. known adult domains (subdomains match too)
ADULT_DOMAINS = frozenset("""
pornhub.com pornhub.org xvideos.com xvideos2.com xvideos3.com xnxx.com xnxx.tv xhamster.com xhamster.desi
xhamster2.com xhamster3.com redtube.com youporn.com youporngay.com tube8.com spankbang.com eporner.com beeg.com
tnaflix.com thumbzilla.com motherless.com txxx.com hclips.com hdzog.com upornia.com vporn.com porntrex.com
pornone.com drtuber.com sunporno.com 4tube.com youjizz.com hqporner.com daftsex.com fuq.com porn.com sex.com
xtube.com pornpics.com porndig.com fapello.com fapality.com chaturbate.com stripchat.com bongacams.com
livejasmin.com cam4.com myfreecams.com camsoda.com flirt4free.com onlyfans.com fansly.com brazzers.com
realitykings.com bangbros.com naughtyamerica.com mofos.com kink.com nhentai.net nhentai.to hentaihaven.xxx
hanime.tv hentaivn.net e-hentai.org exhentai.org rule34.xxx rule34.paheal.net rule34video.com gelbooru.com
literotica.com adultfriendfinder.com
""".split())

# ---------------------------------------------------------------- 2. keywords
# Anywhere in the site name. Only words that almost never appear in an innocent name.
ADULT_SUBSTRINGS = ("porn", "xxx", "hentai", "xvideo", "xnxx", "xhamster", "redtube", "youporn", "nsfw",
                    "camgirl", "erotic", "fuck", "blowjob", "nudes")
# Whole words between dots/hyphens ("sex-videos.com" yes, "essex.ac.uk" no).
ADULT_TOKENS = frozenset("""
sex sexy sexcam sexcams sexvideo sexvideos sextube sexchat sexmovies milf boobs pussy bdsm fetish fap
""".split())
# Whole words in the path ("/porn/clip.mp4"). Only the strongest ones, a path is full of random text.
ADULT_PATH_TOKENS = frozenset("porn porno pornhub xxx hentai nsfw xvideos xnxx xhamster".split())

# ---------------------------------------------------------------- 3. unsafe-link signs
# Endings that are used for scams and malware far more than for real video sites.
SUSPICIOUS_TLDS = frozenset("""
tk ml ga cf gq top click loan zip mov country kim men party review date download racing win bid accountant
cricket faith gdn xin
""".split())
LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet")
_NUMERIC_HOST = re.compile(r"^(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*$")  # 2130706433, 0x7f.1 ... = disguised IPs


def load_domain_list(path: Path) -> frozenset:
    """Reads one domain per line ('#' starts a comment). A full link or '*.example.com' is accepted too."""
    out = set()
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return frozenset()
    for line in lines:
        line = line.split("#", 1)[0].strip().lower()
        if not line:
            continue
        if "://" in line:
            line = urlparse(line).hostname or ""
        line = line.lstrip("*.").rstrip(".")
        if line:
            out.add(line)
    return frozenset(out)


def _parse(url: Optional[str]):
    """Returns (parsed url, lower-case host) or (None, '') for something that is not a usable link."""
    try:
        u = urlparse((url or "").strip())
        return u, (u.hostname or "").rstrip(".").lower()
    except ValueError:
        return None, ""


def _in(host: str, domains: Iterable[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def is_adult(url: Optional[str], extra_blocked: Iterable[str] = (), allowed: Iterable[str] = ()) -> bool:
    u, host = _parse(url)
    if not host:
        return False
    if _in(host, ADULT_DOMAINS) or _in(host, extra_blocked):
        return True
    if _in(host, allowed):
        return False
    if any(s in host for s in ADULT_SUBSTRINGS):
        return True
    if set(re.split(r"[.\-_]+", host)) & ADULT_TOKENS:
        return True
    return bool(set(re.split(r"[^a-z0-9]+", unquote(u.path).lower())) & ADULT_PATH_TOKENS)


def suspicious_reason(url: Optional[str], allowed: Iterable[str] = ()) -> Optional[str]:
    """Returns why a link looks unsafe, or None."""
    u, host = _parse(url)
    if u is None:
        return "the link is malformed"
    if not host:
        return "the link has no site name"
    if u.username or u.password:  # https://trusted.com@evil.com/ : a classic phishing trick
        return "the link hides the real site behind a 'name@' part"
    if _in(host, allowed):
        return None

    ip = None
    try:
        ip = ipaddress.ip_address(host)
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
    except ValueError:
        if _NUMERIC_HOST.match(host):
            return "the link uses a disguised IP address"
    if ip is not None:
        if not ip.is_global:
            return "the link points to your own computer or local network"
        return "the link uses a bare IP address instead of a site name"
    if "." not in host or host.endswith(LOCAL_SUFFIXES):
        return "the link points to your own computer or local network"
    labels = host.split(".")
    if any(label.startswith("xn--") for label in labels):
        return "the site name uses look-alike (punycode) characters"
    if labels[-1] in SUSPICIOUS_TLDS:
        return f"the .{labels[-1]} ending is widely used by scam and malware sites"
    return None


def check_download(url: str, *, tab_url: str = "", page_url: str = "", headers: Optional[dict] = None,
                   extra_blocked: Iterable[str] = (), allowed: Iterable[str] = ()) -> Optional[str]:
    """Returns the reason to refuse a download, or None when it may go on.

    url / tab_url are the file or page the user is downloading from: adult AND unsafe checks apply.
    page_url, Referer and Origin are the frame that played the video: only the adult check applies,
    because an innocent page may embed a player from an odd domain.
    """
    extra_blocked, allowed = frozenset(extra_blocked), frozenset(allowed)
    main = [x for x in (url, tab_url) if x]
    side = [page_url] + [v for k, v in (headers or {}).items() if str(k).lower() in ("referer", "origin")]
    for x in main + [s for s in side if s]:
        if is_adult(x, extra_blocked, allowed):
            return ADULT_MESSAGE
    for x in main:
        why = suspicious_reason(x, allowed)
        if why:
            return f"Blocked: this link looks unsafe ({why})."
    return None
