"""Polling loop for Bilibili updates."""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import time
from typing import Iterable, List

from . import bilibili
from .bilibili import SHANGHAI_TZ
from .config import BilibiliUserConfig, Config
from .notifiers import build_notifiers, notify_all
from .state import State

logger = logging.getLogger(__name__)


class BilibiliMonitor:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = State(config.state_file)
        bilibili.apply_auth_cookies(config.auth_cookies)
        self.notifiers = build_notifiers(config)

    def _iter_new_items(self, user: BilibiliUserConfig) -> Iterable[bilibili.ContentItem]:
        fetch_options = dataclasses.asdict(user.fetch)
        items: List[bilibili.ContentItem] = []
        fetch_plan = [
            ("dynamic", bilibili.fetch_dynamic),
            ("video", bilibili.fetch_videos),
            ("article", bilibili.fetch_articles),
        ]
        for key, fetcher in fetch_plan:
            if not fetch_options.get(key, True):
                continue
            try:
                items.extend(fetcher(user.mid))
            except RuntimeError as exc:
                message = str(exc)
                if "-352" in message:
                    logger.warning(
                        "Bilibili risk control triggered for %s (%s); consider adding cookies",
                        user.name or user.mid,
                        key,
                    )
                    continue
                if "-799" in message:
                    logger.warning(
                        "Rate limited fetching %s for %s; will retry next cycle",
                        key,
                        user.name or user.mid,
                    )
                    continue
                raise
        # Sort so that notifications go from oldest to newest.
        fallback_time = dt.datetime.min.replace(tzinfo=SHANGHAI_TZ)
        items.sort(key=lambda i: i.published_at or fallback_time)
        if items and not self.state.has_entries(user.mid):
            logger.info(
                "Priming state for %s with %d existing items; skipping notifications",
                user.name or user.mid,
                len(items),
            )
            self.state.bulk_remember(
                (user.mid, item.category, item.item_id) for item in items
            )
            return
        for item in items:
            if self.state.is_seen(user.mid, item.category, item.item_id):
                continue
            yield item

    def run_once(self) -> None:
        for user in self.config.bilibili_users:
            display_name = user.name or str(user.mid)
            try:
                for item in self._iter_new_items(user):
                    logger.info("New %s from %s: %s", item.category, display_name, item.title)
                    notify_all(self.notifiers, item)
                    self.state.remember(user.mid, item.category, item.item_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to process user %s: %s", display_name, exc)
        self.state.save()

    def run_forever(self) -> None:
        logger.info("Starting monitor for %s users", len(self.config.bilibili_users))
        while True:
            start = time.time()
            self.run_once()
            elapsed = time.time() - start
            sleep_for = max(0.0, self.config.poll_interval_seconds - elapsed)
            if sleep_for:
                logger.debug("Sleeping for %.2f seconds", sleep_for)
                time.sleep(sleep_for)


__all__ = ["BilibiliMonitor"]
