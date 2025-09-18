"""Notification backends."""
from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Iterable, List, Sequence

import requests

from .bilibili import ContentItem
from .config import Config

logger = logging.getLogger(__name__)


SERVERCHAN_API = "https://sctapi.ftqq.com/{sendkey}.send"


class Notifier(ABC):
    """Base class for notification backends."""

    @abstractmethod
    def send(self, item: ContentItem) -> None:
        raise NotImplementedError


class TelegramNotifier(Notifier):
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, item: ContentItem) -> None:
        text = "\n".join(item.to_notification_lines())
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": False,
        }
        response = requests.post(url, json=payload, timeout=10)
        try:
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - we want to log and continue
            logger.error("Telegram notification failed for %s: %s", item.url, exc)
            return
        if not data.get("ok"):
            logger.error("Telegram API error: %s", data)


class EmailNotifier(Notifier):
    def __init__(
        self,
        host: str,
        port: int,
        use_tls: bool,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: Sequence[str],
    ) -> None:
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = list(to_addrs)

    def send(self, item: ContentItem) -> None:
        if not self.to_addrs:
            logger.warning("No target email addresses configured; skipping notification")
            return
        message = EmailMessage()
        message["Subject"] = f"{item.category}更新: {item.title}"
        message["From"] = self.from_addr
        message["To"] = ", ".join(self.to_addrs)
        message.set_content("\n".join(item.to_notification_lines()))

        try:
            if self.use_tls:
                with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                    smtp.starttls()
                    smtp.login(self.username, self.password)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                    smtp.login(self.username, self.password)
                    smtp.send_message(message)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send email notification for %s: %s", item.url, exc)


class ServerChanNotifier(Notifier):
    def __init__(self, sendkey: str) -> None:
        self.sendkey = sendkey

    def send(self, item: ContentItem) -> None:
        title = f"{item.category}更新: {item.title}"
        desp = "\n".join(item.to_notification_lines())
        url = SERVERCHAN_API.format(sendkey=self.sendkey)
        try:
            response = requests.post(url, data={"title": title, "desp": desp}, timeout=10)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                logger.error("ServerChan API error: %s", payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send ServerChan notification for %s: %s", item.url, exc)


def build_notifiers(config: Config) -> List[Notifier]:
    notifiers: List[Notifier] = []

    if config.notifications.telegram.enabled:
        t_cfg = config.notifications.telegram
        if not (t_cfg.bot_token and t_cfg.chat_id):
            logger.warning("Telegram notifier enabled but bot_token/chat_id missing")
        else:
            notifiers.append(TelegramNotifier(t_cfg.bot_token, t_cfg.chat_id))

    if config.notifications.email.enabled:
        e_cfg = config.notifications.email
        missing = [
            name
            for name, value in (
                ("smtp_host", e_cfg.smtp_host),
                ("username", e_cfg.username),
                ("password", e_cfg.password),
                ("from_addr", e_cfg.from_addr),
            )
            if not value
        ]
        if missing:
            logger.warning("Email notifier enabled but missing fields: %s", ", ".join(missing))
        else:
            notifiers.append(
                EmailNotifier(
                    host=e_cfg.smtp_host,
                    port=e_cfg.smtp_port,
                    use_tls=e_cfg.use_tls,
                    username=e_cfg.username,
                    password=e_cfg.password,
                    from_addr=e_cfg.from_addr,
                    to_addrs=e_cfg.to_addrs,
                )
            )

    if config.notifications.serverchan.enabled:
        s_cfg = config.notifications.serverchan
        if not s_cfg.sendkey:
            logger.warning("ServerChan notifier enabled but sendkey missing")
        else:
            notifiers.append(ServerChanNotifier(s_cfg.sendkey))

    return notifiers


def notify_all(notifiers: Iterable[Notifier], item: ContentItem) -> None:
    for notifier in notifiers:
        try:
            notifier.send(item)
        except Exception as exc:  # noqa: BLE001
            logger.error("Notifier %s crashed for %s: %s", notifier.__class__.__name__, item.url, exc)


__all__ = [
    "Notifier",
    "TelegramNotifier",
    "EmailNotifier",
    "ServerChanNotifier",
    "build_notifiers",
    "notify_all",
]
