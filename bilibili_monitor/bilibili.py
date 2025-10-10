"""Bilibili API client helpers."""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import hmac
import io
import json
import logging
import random
import struct
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Tuple, Union

from zoneinfo import ZoneInfo

import os
from curl_cffi import requests as cffi_requests

from .config import AuthCookies

logger = logging.getLogger(__name__)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bilibili.com",
    "Connection": "keep-alive",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "sec-ch-ua": '"Chromium";v="131", "Not=A?Brand";v="24", "Google Chrome";v="131"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


_SESSION = cffi_requests.Session(
    impersonate="chrome",
    timeout=12,
    verify=True,
    trust_env=False,
)
_SESSION.proxies = None
_SESSION.headers.update(DEFAULT_HEADERS)


def _seed_basic_cookies() -> None:
    """Populate baseline cookies that mimic browser defaults."""

    now_ms = str(int(time.time() * 1000))
    _SESSION.cookies.set("b_nut", now_ms, domain=".bilibili.com", path="/")
    _SESSION.cookies.set("i-wanna-go-back", "-1", domain=".bilibili.com", path="/")
    _SESSION.cookies.set("CURRENT_FNVAL", "128", domain=".bilibili.com", path="/")
    _SESSION.cookies.set("CURRENT_QUALITY", "80", domain=".bilibili.com", path="/")
    _SESSION.cookies.set("hit-dyn-v2", "1", domain=".bilibili.com", path="/")
    _SESSION.cookies.set(
        "b_lsid",
        f"{uuid.uuid4().hex}_{now_ms}",
        domain=".bilibili.com",
        path="/",
    )
    _SESSION.cookies.set("rpdid", f"|{uuid.uuid4().hex[:11]}|{uuid.uuid4().hex[:11]}|", domain=".bilibili.com", path="/")


_seed_basic_cookies()


_AUTH_COOKIE_MAPPING = {
    "sessdata": "SESSDATA",
    "bili_jct": "bili_jct",
    "buvid3": "buvid3",
    "buvid4": "buvid4",
    "dedeuserid": "DedeUserID",
    "dedeuserid_ckmd5": "DedeUserID__ckMd5",
}


def apply_auth_cookies(cookies: Union[AuthCookies, Mapping[str, Optional[str]], None]) -> None:
    """Update the shared session with authenticated cookies if provided."""

    if not cookies:
        return

    if isinstance(cookies, Mapping):
        source = cookies
    else:
        source = {
            field.name: getattr(cookies, field.name)
            for field in dataclasses.fields(AuthCookies)
        }

    for field_name, cookie_name in _AUTH_COOKIE_MAPPING.items():
        value = source.get(field_name)
        if not value:
            continue
        _SESSION.cookies.set(cookie_name, value, domain=".bilibili.com", path="/")


_BUVID_FETCHED = False
_BUVID_PAIR: Optional[Tuple[str, str]] = None
_BILI_TICKET: Optional[str] = None
_BILI_TICKET_EXPIRES_AT: int = 0


_WBI_MIXIN_KEY_ORDER = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    13,
    41,
    3,
    10,
    34,
    6,
    29,
    58,
    45,
    4,
    14,
    57,
    12,
    37,
    27,
    43,
    5,
    49,
    26,
    38,
    54,
    63,
    9,
    7,
    61,
    21,
    48,
    32,
    16,
    50,
    28,
    15,
    39,
    56,
    62,
    35,
    1,
    60,
    59,
    24,
    40,
    44,
    30,
    52,
    0,
    33,
    51,
    22,
    31,
    19,
    11,
    36,
    55,
    25,
    17,
    42,
    20,
]

_WBI_MIXIN_KEY: Optional[str] = None
_WBI_LAST_FETCHED: float = 0.0


def _rotate_left(value: int, bits: int) -> int:
    return ((value << bits) & ((1 << 64) - 1)) | (value >> (64 - bits))


def _murmur3_x64_128(data: bytes, seed: int) -> int:
    modulus = 1 << 64
    c1 = 0x87C37B91114253D5
    c2 = 0x4CF5AD432745937F
    c3 = 0x52DCE729
    c4 = 0x38495AB5
    r1, r2, r3 = 27, 31, 33
    h1 = seed
    h2 = seed
    processed = 0
    stream = io.BytesIO(data)
    while True:
        chunk = stream.read(16)
        processed += len(chunk)
        if len(chunk) == 16:
            k1 = struct.unpack("<q", chunk[:8])[0]
            k2 = struct.unpack("<q", chunk[8:])[0]
            h1 ^= _rotate_left((k1 * c1) % modulus, r2) * c2 % modulus
            h1 = ((_rotate_left(h1, r1) + h2) * 5 + c3) % modulus
            h2 ^= _rotate_left((k2 * c2) % modulus, r3) * c1 % modulus
            h2 = ((_rotate_left(h2, r2) + h1) * 5 + c4) % modulus
        elif len(chunk) == 0:
            h1 ^= processed
            h2 ^= processed
            h1 = (h1 + h2) % modulus
            h2 = (h2 + h1) % modulus
            h1 = _fmix64(h1)
            h2 = _fmix64(h2)
            h1 = (h1 + h2) % modulus
            h2 = (h2 + h1) % modulus
            return (h2 << 64) | h1
        else:
            tail = chunk + b"\x00" * (16 - len(chunk))
            k1 = 0
            k2 = 0
            if len(chunk) >= 15:
                k2 ^= tail[14] << 48
            if len(chunk) >= 14:
                k2 ^= tail[13] << 40
            if len(chunk) >= 13:
                k2 ^= tail[12] << 32
            if len(chunk) >= 12:
                k2 ^= tail[11] << 24
            if len(chunk) >= 11:
                k2 ^= tail[10] << 16
            if len(chunk) >= 10:
                k2 ^= tail[9] << 8
            if len(chunk) >= 9:
                k2 ^= tail[8]
                k2 = _rotate_left((k2 * c2) % modulus, r3) * c1 % modulus
                h2 ^= k2
            if len(chunk) >= 8:
                k1 ^= tail[7] << 56
            if len(chunk) >= 7:
                k1 ^= tail[6] << 48
            if len(chunk) >= 6:
                k1 ^= tail[5] << 40
            if len(chunk) >= 5:
                k1 ^= tail[4] << 32
            if len(chunk) >= 4:
                k1 ^= tail[3] << 24
            if len(chunk) >= 3:
                k1 ^= tail[2] << 16
            if len(chunk) >= 2:
                k1 ^= tail[1] << 8
            if len(chunk) >= 1:
                k1 ^= tail[0]
                k1 = _rotate_left((k1 * c1) % modulus, r2) * c2 % modulus
                h1 ^= k1


def _fmix64(value: int) -> int:
    value ^= value >> 33
    value = (value * 0xFF51AFD7ED558CCD) % (1 << 64)
    value ^= value >> 33
    value = (value * 0xC4CEB9FE1A85EC53) % (1 << 64)
    value ^= value >> 33
    return value


def _gen_uuid_infoc() -> str:
    suffix = str(int(time.time() * 1000) % 100000).ljust(5, "0")
    parts = [8, 4, 4, 4, 12]
    charset = "123456789ABCDEF0"
    chunks = ["".join(random.choice(charset) for _ in range(length)) for length in parts]
    return f"{'-'.join(chunks)}{suffix}infoc"


def _gen_b_lsid() -> str:
    prefix = "".join(random.choice("0123456789ABCDEF") for _ in range(8))
    return f"{prefix}_{hex(int(time.time() * 1000))[2:].upper()}"


def _gen_buvid_fp(payload: str, seed: int) -> str:
    digest = _murmur3_x64_128(payload.encode("ascii"), seed)
    low = hex(digest & ((1 << 64) - 1))[2:]
    high = hex(digest >> 64)[2:]
    return f"{low}{high}"


def _request_json(url: str, *, method: str = "GET", params: Optional[Dict[str, str]] = None, data: Optional[Union[Dict, str]] = None, headers: Optional[Dict[str, str]] = None) -> Dict:
    response = _SESSION.request(method, url, params=params, data=data, headers=headers, timeout=12)
    response.raise_for_status()
    return response.json()


def _fetch_buvid_pair() -> Tuple[str, str]:
    payload = _request_json(
        "https://api.bilibili.com/x/frontend/finger/spi",
        headers=DEFAULT_HEADERS,
    )
    data = payload.get("data") or {}
    buvid3 = data.get("b_3")
    buvid4 = data.get("b_4")
    if not buvid3 or not buvid4:
        raise RuntimeError("Failed to fetch buvid3/buvid4 from SPI endpoint")
    return buvid3, buvid4


def _activate_buvid(buvid3: str, buvid4: str) -> None:
    uuid_infoc = _gen_uuid_infoc()
    payload_content = {
        "01bf": "",
        "c881": "",
        "42bf": "927",
        "b4e4": "1",
        "490d": "-120",
        "3009": str(random.randint(600, 800)),
        "b120": str(random.randint(500, 700)),
        "8fa6": "MacIntel",
        "3434": "zh-CN",
        "8534": "Asia/Shanghai",
        "54ef": json.dumps({"in_new_ab": True}),
        "dd9d": "1",
        "770c": "Mac OS",
        "81d3": "",
        "c09f": "",
        "6de2": "",
        "8956": 0,
        "a661": 0,
        "0e7b": 0,
        "7c43": 0,
        "c130": 0,
        "0ef9": 0,
        "8318": 0,
        "69ae": 1,
        "4c4a": "en-US",
        "b0cf": "Google Inc.",
        "75b1": "",
        "d02f": str(80 + random.random() * 30),
        "df35": uuid_infoc,
        "8b94": urllib.parse.quote("https://www.bilibili.com/"),
    }
    payload = json.dumps({"payload": json.dumps(payload_content, separators=(",", ":"))}, separators=(",", ":"))

    buvid_fp = _gen_buvid_fp(payload, 31)
    headers = DEFAULT_HEADERS.copy()
    headers["Content-Type"] = "application/json"
    cookies = {
        "buvid3": buvid3,
        "buvid4": buvid4,
        "buvid_fp": buvid_fp,
        "_uuid": uuid_infoc,
    }
    result = _SESSION.post(
        "https://api.bilibili.com/x/internal/gaia-gateway/ExClimbWuzhi",
        data=payload,
        headers=headers,
        cookies=cookies,
        timeout=12,
    )
    result.raise_for_status()
    resp = result.json()
    if resp.get("code") != 0:
        raise RuntimeError(f"Failed to activate buvid: {resp}")
    _SESSION.cookies.set("buvid_fp", buvid_fp, domain=".bilibili.com", path="/")


def _ensure_buvid() -> None:
    global _BUVID_FETCHED, _BUVID_PAIR
    if _BUVID_FETCHED:
        return
    existing3 = _SESSION.cookies.get("buvid3")
    existing4 = _SESSION.cookies.get("buvid4")
    if existing3 and existing4:
        _SESSION.cookies.set("buvid3", existing3, domain=".bilibili.com", path="/")
        _SESSION.cookies.set("buvid4", existing4, domain=".bilibili.com", path="/")
        _SESSION.cookies.set("opus-goback", "1", domain=".bilibili.com", path="/")
        _BUVID_PAIR = (existing3, existing4)
        _BUVID_FETCHED = True
        return
    try:
        buvid3, buvid4 = _fetch_buvid_pair()
        _activate_buvid(buvid3, buvid4)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to obtain activated buvid pair: %s", exc)
        buvid3 = f"{uuid.uuid4().hex[:8]}infoc"
        buvid4 = f"{uuid.uuid4().hex[:8]}infoc"
        _SESSION.cookies.set("buvid_fp", uuid.uuid4().hex, domain=".bilibili.com", path="/")
    _SESSION.cookies.set("buvid3", buvid3, domain=".bilibili.com", path="/")
    _SESSION.cookies.set("buvid4", buvid4, domain=".bilibili.com", path="/")
    _SESSION.cookies.set("opus-goback", "1", domain=".bilibili.com", path="/")
    _BUVID_PAIR = (buvid3, buvid4)
    _BUVID_FETCHED = True


def _ensure_bili_ticket() -> None:
    global _BILI_TICKET, _BILI_TICKET_EXPIRES_AT
    now = int(time.time())
    if _BILI_TICKET and now < _BILI_TICKET_EXPIRES_AT - 60:
        return
    try:
        ts = int(time.time())
        hexsign = hmac.new(b"XgwSnGZ1p", f"ts{ts}".encode("utf-8"), hashlib.sha256).hexdigest()
        params = {
            "key_id": "ec02",
            "hexsign": hexsign,
            "context[ts]": str(ts),
            "csrf": "",
        }
        payload = _request_json(
            "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket",
            method="POST",
            params=params,
            headers=DEFAULT_HEADERS,
        )
        ticket = (payload.get("data") or {}).get("ticket")
        if ticket:
            _BILI_TICKET = ticket
            _BILI_TICKET_EXPIRES_AT = ts + 3 * 24 * 60 * 60
            _SESSION.cookies.set("bili_ticket", ticket, domain=".bilibili.com", path="/")
            _SESSION.cookies.set(
                "bili_ticket_expires",
                str(_BILI_TICKET_EXPIRES_AT),
                domain=".bilibili.com",
                path="/",
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to refresh bili_ticket: %s", exc)


def _prepare_session() -> None:
    _ensure_buvid()
    _ensure_bili_ticket()


def _extract_wbi_key(url: str) -> str:
    return url.rsplit("/", 1)[-1].split(".")[0]


def _compute_wbi_mixin_key() -> str:
    response = _SESSION.get("https://api.bilibili.com/x/web-interface/nav", timeout=10)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or {}
    wbi_img = data.get("wbi_img") or {}
    img_url = wbi_img.get("img_url")
    sub_url = wbi_img.get("sub_url")
    if not (img_url and sub_url):
        raise RuntimeError("Failed to obtain wbi mixin key from nav response")
    raw_key = _extract_wbi_key(img_url) + _extract_wbi_key(sub_url)
    return "".join(raw_key[idx] for idx in _WBI_MIXIN_KEY_ORDER)[:32]


def _get_wbi_mixin_key(force_refresh: bool = False) -> str:
    global _WBI_MIXIN_KEY, _WBI_LAST_FETCHED
    now = time.time()
    if force_refresh or not _WBI_MIXIN_KEY or now - _WBI_LAST_FETCHED > 3600:
        _WBI_MIXIN_KEY = _compute_wbi_mixin_key()
        _WBI_LAST_FETCHED = now
    return _WBI_MIXIN_KEY


def _inject_wbi_mouse(params: Dict[str, str]) -> None:
    dm_rand = "ABCDEFGHIJK"
    params.setdefault("dm_img_list", "[]")
    params.setdefault("dm_img_str", "".join(random.sample(dm_rand, 2)))
    params.setdefault("dm_cover_img_str", "".join(random.sample(dm_rand, 2)))
    params.setdefault("dm_img_inter", '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}')


def _sign_wbi_params(params: Dict[str, str], *, include_mouse: bool = False) -> Dict[str, str]:
    mixin_key = _get_wbi_mixin_key()
    filtered: Dict[str, str] = {
        key: "".join(ch for ch in str(value) if ch not in "!'()*")
        for key, value in params.items()
        if value is not None
    }
    if include_mouse:
        _inject_wbi_mouse(filtered)
    filtered.setdefault("web_location", 1550101)
    filtered["wts"] = str(int(time.time()))
    ordered = dict(sorted(filtered.items()))
    query = urllib.parse.urlencode(ordered)
    ordered["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return ordered


@dataclass
class ContentItem:
    """Normalized representation of a Bilibili publication."""

    category: str
    item_id: str
    title: str
    url: str
    author: Optional[str]
    published_at: Optional[dt.datetime]
    summary: Optional[str] = None

    def to_notification_lines(self) -> List[str]:
        published = (
            self.published_at.astimezone(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
            if self.published_at
            else "未知时间"
        )
        lines = [
            f"[{self.category}] {self.title}",
            f"作者: {self.author or '未知'}",
            f"时间: {published}",
            f"链接: {self.url}",
        ]
        if self.summary:
            lines.append(f"内容: {self.summary}")
        return lines


def _raise_for_code(payload: Dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected response payload: {payload!r}")
    code = payload.get("code")
    if code not in (0, None):
        message = payload.get("message") or payload.get("msg") or "unknown error"
        raise RuntimeError(f"Bilibili API error {code}: {message}")


def _safe_datetime(ts: Optional[int]) -> Optional[dt.datetime]:
    if not ts:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ts), tz=SHANGHAI_TZ)
    except (TypeError, ValueError, OSError):
        return None


def fetch_dynamic(mid: int, limit: int = 20) -> List[ContentItem]:
    """Fetch latest dynamic items for the given user id."""
    _prepare_session()
    url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
    params = {
        "host_mid": str(mid),
        "timezone_offset": "-480",
        "features": "itemOpusStyle",
    }
    headers = DEFAULT_HEADERS.copy()
    headers["Referer"] = f"https://space.bilibili.com/{mid}/dynamic"
    headers["Origin"] = "https://space.bilibili.com"
    response = _SESSION.get(url, params=params, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    _raise_for_code(data)
    items = data.get("data", {}).get("items") or []

    results: List[ContentItem] = []
    for raw in items[:limit]:
        item_id = raw.get("id_str") or raw.get("id")
        modules = raw.get("modules") or {}
        author = modules.get("module_author", {}).get("name")
        dynamic_module = modules.get("module_dynamic") or {}
        major = dynamic_module.get("major") or {}
        desc_module = dynamic_module.get("desc") or {}

        title = None
        summary = None
        url_item = None

        if major.get("type") == "MAJOR_TYPE_ARCHIVE":
            archive = major.get("archive") or {}
            title = archive.get("title") or "动态投稿"
            bvid = archive.get("bvid")
            url_item = f"https://www.bilibili.com/video/{bvid}" if bvid else None
            summary = archive.get("desc")
        elif major.get("type") == "MAJOR_TYPE_ARTICLE":
            article = major.get("article") or {}
            title = article.get("title") or "专栏文章"
            url_item = article.get("jump_url")
            summary = article.get("desc")
        elif major.get("type") == "MAJOR_TYPE_LIVE":
            live = major.get("live_rcmd") or {}
            title = live.get("title") or "直播动态"
            url_item = live.get("link")
            summary = live.get("content")
        elif major.get("type") == "MAJOR_TYPE_OPUS":
            opus = major.get("opus") or {}
            title = opus.get("title") or "图文动态"
            jump_url = opus.get("jump_url")
            if jump_url:
                url_item = jump_url if not str(jump_url).startswith("//") else f"https:{jump_url}"
            summary_data = opus.get("summary") or {}
            summary = summary_data.get("text")
            if not summary:
                nodes = summary_data.get("rich_text_nodes") or []
                summary = "".join(node.get("text") or "" for node in nodes)
            if not summary:
                summary = desc_module.get("text")
        elif dynamic_module.get("type") == "DYNAMIC_TYPE_WORD":
            title = desc_module.get("text") or "文字动态"
            summary = title

        if not title:
            title = desc_module.get("text") or raw.get("type") or "动态"
            summary = summary or desc_module.get("text")

        if not url_item:
            url_item = f"https://t.bilibili.com/{item_id}" if item_id else "https://t.bilibili.com/"

        published = None
        if modules.get("module_author"):
            published = _safe_datetime(modules["module_author"].get("pub_ts"))

        if not item_id:
            # Fall back to hashed title timestamp to keep dedupe working reasonably.
            item_id = f"dynamic-{mid}-{modules.get('module_author', {}).get('pub_ts', '0')}"

        results.append(
            ContentItem(
                category="动态",
                item_id=str(item_id),
                title=str(title),
                url=url_item,
                author=author,
                published_at=published,
                summary=summary,
            )
        )
    return results


def fetch_videos(mid: int, limit: int = 10) -> List[ContentItem]:
    """Fetch latest submitted videos for the given user id."""
    _prepare_session()
    url = "https://api.bilibili.com/x/space/arc/search"
    base_params = {
        "mid": str(mid),
        "pn": "1",
        "ps": str(limit),
        "platform": "web",
    }
    headers = DEFAULT_HEADERS.copy()
    headers["Referer"] = f"https://space.bilibili.com/{mid}/video"
    headers["Origin"] = "https://space.bilibili.com"
    data = None
    for attempt in range(2):
        params = _sign_wbi_params(base_params, include_mouse=True)
        response = _SESSION.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        try:
            _raise_for_code(data)
            break
        except RuntimeError as exc:
            if "-799" in str(exc) and attempt == 0:
                logger.debug("Refreshing WBI mixin key after -799 response for videos")
                _get_wbi_mixin_key(force_refresh=True)
                time.sleep(0.5)
                continue
            raise
    if data is None:
        raise RuntimeError("Failed to fetch videos: empty response")
    vlist = data.get("data", {}).get("list", {}).get("vlist") or []

    results: List[ContentItem] = []
    for raw in vlist:
        bvid = raw.get("bvid")
        aid = raw.get("aid")
        title = raw.get("title") or "视频投稿"
        description = raw.get("description")
        created = _safe_datetime(raw.get("created"))
        url_item = f"https://www.bilibili.com/video/{bvid}" if bvid else f"https://www.bilibili.com/video/av{aid}"
        author = raw.get("author")
        item_id = bvid or str(aid)

        results.append(
            ContentItem(
                category="视频",
                item_id=str(item_id),
                title=str(title),
                url=url_item,
                author=author,
                published_at=created,
                summary=description,
            )
        )
    return results


def fetch_articles(mid: int, limit: int = 10) -> List[ContentItem]:
    """Fetch latest articles for the given user id."""
    _prepare_session()
    url = "https://api.bilibili.com/x/space/article"
    base_params = {
        "mid": str(mid),
        "pn": "1",
        "ps": str(limit),
        "sort": "publish_time",
    }
    headers = DEFAULT_HEADERS.copy()
    headers["Referer"] = f"https://space.bilibili.com/{mid}/article"
    headers["Origin"] = "https://space.bilibili.com"
    data = None
    for attempt in range(2):
        params = _sign_wbi_params(base_params, include_mouse=True)
        response = _SESSION.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        try:
            _raise_for_code(data)
            break
        except RuntimeError as exc:
            if "-799" in str(exc) and attempt == 0:
                logger.debug("Refreshing WBI mixin key after -799 response for articles")
                _get_wbi_mixin_key(force_refresh=True)
                time.sleep(0.5)
                continue
            raise
    if data is None:
        raise RuntimeError("Failed to fetch articles: empty response")
    articles = data.get("data", {}).get("articles") or []

    results: List[ContentItem] = []
    for raw in articles[:limit]:
        cvid = raw.get("id") or raw.get("cvid")
        title = raw.get("title") or "专栏文章"
        summary = raw.get("summary")
        publish_time = _safe_datetime(raw.get("publish_time"))
        url_item = f"https://www.bilibili.com/read/cv{cvid}"
        author = raw.get("author_name")

        results.append(
            ContentItem(
                category="专栏",
                item_id=str(cvid),
                title=str(title),
                url=url_item,
                author=author,
                published_at=publish_time,
                summary=summary,
            )
        )
    return results


def fetch_all_for_user(mid: int, fetch_options: Dict[str, bool]) -> Iterable[ContentItem]:
    """Fetch every requested category for the given user."""
    if fetch_options.get("dynamic", True):
        yield from fetch_dynamic(mid)
    if fetch_options.get("video", True):
        yield from fetch_videos(mid)
    if fetch_options.get("article", True):
        yield from fetch_articles(mid)


__all__ = [
    "ContentItem",
    "fetch_dynamic",
    "fetch_videos",
    "fetch_articles",
    "fetch_all_for_user",
    "apply_auth_cookies",
    "SHANGHAI_TZ",
]
