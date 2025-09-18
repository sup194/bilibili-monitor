"""Persistence helper to keep track of already notified items."""
from __future__ import annotations

import json
import logging
import pathlib
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, Tuple

logger = logging.getLogger(__name__)


@dataclass
class State:
    path: pathlib.Path
    max_ids_per_category: int = 50
    _seen: Dict[str, Dict[str, Deque[str]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.path, pathlib.Path):
            self.path = pathlib.Path(self.path)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._seen = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except Exception as exc:  # noqa: BLE001 - we want to continue even on corrupted files
            logger.warning("Failed to load state file %s: %s", self.path, exc)
            self._seen = {}
            return
        seen: Dict[str, Dict[str, Deque[str]]] = {}
        for mid, categories in raw.items():
            seen[mid] = {}
            for category, ids in categories.items():
                dq: Deque[str] = deque(maxlen=self.max_ids_per_category)
                for item_id in ids:
                    dq.append(str(item_id))
                seen[mid][category] = dq
        self._seen = seen

    def _ensure_deque(self, mid: str, category: str) -> Deque[str]:
        return self._seen.setdefault(mid, {}).setdefault(
            category, deque(maxlen=self.max_ids_per_category)
        )

    def has_entries(self, mid: int) -> bool:
        categories = self._seen.get(str(mid))
        if not categories:
            return False
        return any(categories.values())

    def is_seen(self, mid: int, category: str, item_id: str) -> bool:
        dq = self._seen.get(str(mid), {}).get(category)
        return bool(dq and item_id in dq)

    def remember(self, mid: int, category: str, item_id: str) -> None:
        dq = self._ensure_deque(str(mid), category)
        if item_id not in dq:
            dq.append(item_id)

    def bulk_remember(self, entries: Iterable[Tuple[int, str, str]]) -> None:
        for mid, category, item_id in entries:
            self.remember(mid, category, item_id)

    def save(self) -> None:
        data = {
            mid: {category: list(ids) for category, ids in categories.items()}
            for mid, categories in self._seen.items()
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to save state file %s: %s", self.path, exc)


__all__ = ["State"]
