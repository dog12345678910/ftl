"""The core polling loop that ties scraping, state and notifications together."""

from __future__ import annotations

import datetime as dt
import logging
import random
import time

from . import history
from .config import Config
from .notifiers import Notifier, build_notifiers
from .scraper import Scraper
from .state import RestockEvent, StateStore

log = logging.getLogger(__name__)


class Monitor:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.scraper = Scraper(
            pdp_template=config.pdp_template,
            headers=config.headers,
            cookies=config.cookies,
            proxies=config.proxies or None,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )
        self.state = StateStore(config.state_file, track_price_drops=config.track_price_drops)
        self.notifiers: list[Notifier] = build_notifiers(config.notifiers)

    # -- one sweep over every watched product ------------------------------

    def check_once(self) -> list[RestockEvent]:
        events: list[RestockEvent] = []
        for i, watched in enumerate(self.config.watch):
            status = self.scraper.fetch(watched)
            if status.error:
                log.warning("[%s] %s", watched.sku, status.error)
            else:
                stock = "IN STOCK" if status.in_stock else "out of stock"
                log.info("[%s] %s — %s", watched.sku, status.name, stock)

            event = self.state.evaluate(watched, status)
            if event and (not event.first_seen or self.config.alert_on_first_seen):
                events.append(event)

            if i < len(self.config.watch) - 1 and self.config.per_product_delay > 0:
                time.sleep(self.config.per_product_delay)

        self.state.save()
        history.append_events(self.config.history_file, events)
        for event in events:
            self._dispatch(event)
        return events

    def _dispatch(self, event: RestockEvent) -> None:
        for notifier in self.notifiers:
            try:
                notifier.notify(event)
            except Exception as exc:  # noqa: BLE001 - never let one channel kill the loop
                log.warning("Notifier %s failed: %s", type(notifier).__name__, exc)

    # -- continuous "throughout the day" loop ------------------------------

    def run_forever(self) -> None:
        log.info(
            "Monitoring %d product(s) every ~%ds. Press Ctrl+C to stop.",
            len(self.config.watch),
            self.config.interval_seconds,
        )
        try:
            while True:
                if self._within_active_hours():
                    try:
                        self.check_once()
                    except Exception as exc:  # noqa: BLE001 - keep the loop alive
                        log.exception("Sweep failed: %s", exc)
                    sleep_for = self.config.interval_seconds + random.uniform(
                        0, max(0, self.config.jitter_seconds)
                    )
                else:
                    log.info("Outside active hours; sleeping.")
                    sleep_for = 300
                time.sleep(sleep_for)
        except KeyboardInterrupt:
            log.info("Stopped by user.")

    def _within_active_hours(self) -> bool:
        start = self.config.active_start_hour
        end = self.config.active_end_hour
        if start is None or end is None:
            return True
        hour = dt.datetime.now().hour
        if start <= end:
            return start <= hour < end
        # Window wraps past midnight (e.g. 22 -> 6).
        return hour >= start or hour < end
