"""Command-line entrypoint for the Foot Locker restock monitor."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Config
from .monitor import Monitor
from .product import WatchedProduct


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="footlocker-monitor",
        description="Monitor Foot Locker for restocks throughout the day.",
    )
    parser.add_argument(
        "-c", "--config", default="config.json",
        help="Path to the JSON config file (default: config.json).",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single check and exit (useful for cron).",
    )
    parser.add_argument(
        "--watch", metavar="URL_OR_SKU", action="append", default=[],
        help="Ad-hoc product URL or SKU to watch (repeatable). "
             "Skips the config file's watch list if provided.",
    )
    parser.add_argument(
        "--interval", type=int, default=None,
        help="Override the base poll interval, in seconds.",
    )
    parser.add_argument(
        "--dashboard", action="store_true",
        help="Serve a live web dashboard while monitoring.",
    )
    parser.add_argument(
        "--serve-only", action="store_true",
        help="With --dashboard, show the dashboard without running the monitor "
             "loop (e.g. to view state written by another process).",
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port for the --dashboard web server (default: 8000).",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Bind address for the --dashboard server (default: 0.0.0.0; "
             "use 127.0.0.1 to restrict to this machine).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging.",
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    if args.watch:
        # Build a minimal config purely from --watch flags.
        config = Config(watch=[WatchedProduct.from_url_or_sku(w) for w in args.watch])
    else:
        config = Config.load(args.config)

    if args.interval is not None:
        config.interval_seconds = args.interval
    return config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = _config_from_args(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.dashboard:
        from .dashboard import serve

        # Persist UI edits back to the config file when one is in use.
        config_path = None if args.watch else args.config
        serve(
            config,
            port=args.port,
            host=args.host,
            run_monitor=not args.serve_only,
            config_path=config_path,
        )
        return 0

    monitor = Monitor(config)
    if args.once:
        events = monitor.check_once()
        logging.getLogger(__name__).info("Done. %d restock alert(s).", len(events))
    else:
        monitor.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
