from __future__ import annotations

import argparse
import logging
import pathlib
import sys

from bilibili_monitor.config import load_config
from bilibili_monitor.poller import BilibiliMonitor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor Bilibili users and send notifications")
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        default=pathlib.Path("config.yaml"),
        help="Path to configuration YAML file (default: config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single polling cycle instead of the continuous loop",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: INFO)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        config = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        logging.error("Failed to load config %s: %s", args.config, exc)
        return 1

    monitor = BilibiliMonitor(config)
    if args.once:
        monitor.run_once()
    else:
        monitor.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
