"""Configuration loader for the Bilibili monitor."""
from __future__ import annotations

import dataclasses
import pathlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


@dataclass
class FetchOptions:
    dynamic: bool = True
    video: bool = True
    article: bool = True


@dataclass
class BilibiliUserConfig:
    mid: int
    name: Optional[str] = None
    fetch: FetchOptions = field(default_factory=FetchOptions)


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


@dataclass
class EmailConfig:
    enabled: bool = False
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    use_tls: bool = True
    username: Optional[str] = None
    password: Optional[str] = None
    from_addr: Optional[str] = None
    to_addrs: List[str] = field(default_factory=list)


@dataclass
class ServerChanConfig:
    enabled: bool = False
    sendkey: Optional[str] = None


@dataclass
class NotificationConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    serverchan: ServerChanConfig = field(default_factory=ServerChanConfig)


@dataclass
class AuthCookies:
    sessdata: Optional[str] = None
    bili_jct: Optional[str] = None
    buvid3: Optional[str] = None
    buvid4: Optional[str] = None
    dedeuserid: Optional[str] = None
    dedeuserid_ckmd5: Optional[str] = None


@dataclass
class Config:
    poll_interval_seconds: int = 60
    bilibili_users: List[BilibiliUserConfig] = field(default_factory=list)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    state_file: pathlib.Path = pathlib.Path("state.json")
    auth_cookies: AuthCookies = field(default_factory=AuthCookies)


def _load_fetch_options(raw: Optional[dict]) -> FetchOptions:
    if raw is None:
        return FetchOptions()
    return FetchOptions(
        dynamic=bool(raw.get("dynamic", True)),
        video=bool(raw.get("video", True)),
        article=bool(raw.get("article", True)),
    )


def _load_user_config(raw: dict) -> BilibiliUserConfig:
    try:
        mid = int(raw["mid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid or missing 'mid' in user config: {raw!r}") from exc
    name = raw.get("name")
    fetch = _load_fetch_options(raw.get("fetch"))
    return BilibiliUserConfig(mid=mid, name=name, fetch=fetch)


def _load_telegram_config(raw: Optional[dict]) -> TelegramConfig:
    if raw is None:
        return TelegramConfig()
    return TelegramConfig(
        enabled=bool(raw.get("enabled", False)),
        bot_token=raw.get("bot_token"),
        chat_id=raw.get("chat_id"),
    )


def _load_email_config(raw: Optional[dict]) -> EmailConfig:
    if raw is None:
        return EmailConfig()
    to_addrs = raw.get("to_addrs") or []
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]
    return EmailConfig(
        enabled=bool(raw.get("enabled", False)),
        smtp_host=raw.get("smtp_host"),
        smtp_port=int(raw.get("smtp_port", 587)),
        use_tls=bool(raw.get("use_tls", True)),
        username=raw.get("username"),
        password=raw.get("password"),
        from_addr=raw.get("from_addr"),
        to_addrs=list(to_addrs),
    )


def _load_serverchan_config(raw: Optional[dict]) -> ServerChanConfig:
    if raw is None:
        return ServerChanConfig()
    return ServerChanConfig(
        enabled=bool(raw.get("enabled", False)),
        sendkey=raw.get("sendkey"),
    )


def _load_auth_cookies(raw: Optional[dict]) -> AuthCookies:
    if raw is None:
        return AuthCookies()
    known_fields = {field.name for field in dataclasses.fields(AuthCookies)}
    filtered: Dict[str, Optional[str]] = {
        name: raw.get(name)
        for name in known_fields
        if raw.get(name)
    }
    return AuthCookies(**filtered)


def load_config(path: pathlib.Path) -> Config:
    """Load the YAML config from *path* and return a Config object."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    poll_interval_seconds = int(data.get("poll_interval_seconds", data.get("poll_interval", 60)))

    raw_users = data.get("bilibili_users") or []
    if not raw_users:
        raise ValueError("Config must define at least one entry under 'bilibili_users'.")
    users = [_load_user_config(item) for item in raw_users]

    notifications = data.get("notifications") or {}
    telegram = _load_telegram_config(notifications.get("telegram"))
    email = _load_email_config(notifications.get("email"))
    serverchan = _load_serverchan_config(notifications.get("serverchan"))

    state_file_raw = data.get("state_file", "state.json")
    state_file = pathlib.Path(state_file_raw)

    auth_cookies = _load_auth_cookies(data.get("auth_cookies"))

    return Config(
        poll_interval_seconds=poll_interval_seconds,
        bilibili_users=users,
        notifications=NotificationConfig(telegram=telegram, email=email, serverchan=serverchan),
        state_file=state_file,
        auth_cookies=auth_cookies,
    )
