"""Tests for UI-driven watch management and config persistence."""

import json

import pytest

from footlocker_monitor.config import Config
from footlocker_monitor.dashboard import add_watch, build_status, remove_watch
from footlocker_monitor.product import WatchedProduct


def _config(tmp_path, watch=None):
    return Config(
        watch=watch or [],
        state_file=str(tmp_path / "state.json"),
        history_file=str(tmp_path / "hist.jsonl"),
    )


def test_add_watch_from_url(tmp_path):
    cfg = _config(tmp_path)
    wp = add_watch(cfg, {"input": "https://www.champssports.com/product/~/314206561604.html"})
    assert wp.sku == "314206561604"
    assert wp.retailer == "champssports"
    assert len(cfg.watch) == 1


def test_add_watch_with_sizes_string(tmp_path):
    cfg = _config(tmp_path)
    wp = add_watch(cfg, {"input": "314206561604", "sizes": "9, 9.5, 10"})
    assert wp.sizes == ["9", "9.5", "10"]


def test_add_watch_dedupes_by_sku(tmp_path):
    cfg = _config(tmp_path)
    add_watch(cfg, {"input": "314206561604"})
    add_watch(cfg, {"input": "314206561604", "sizes": "10"})
    assert len(cfg.watch) == 1
    assert cfg.watch[0].sizes == ["10"]


def test_add_watch_rejects_empty(tmp_path):
    cfg = _config(tmp_path)
    with pytest.raises(ValueError):
        add_watch(cfg, {"input": ""})


def test_remove_watch(tmp_path):
    cfg = _config(tmp_path, [WatchedProduct(sku="314206561604")])
    assert remove_watch(cfg, "314206561604") is True
    assert cfg.watch == []
    assert remove_watch(cfg, "nope") is False


def test_config_save_round_trip(tmp_path):
    path = str(tmp_path / "config.json")
    cfg = _config(tmp_path)
    add_watch(cfg, {"input": "https://www.footlocker.com/product/~/314206561604.html", "sizes": "9, 10"})
    cfg.notifiers = [{"type": "discord", "webhook_url": "http://x"}]
    cfg.save(path)

    reloaded = Config.load(path)
    assert len(reloaded.watch) == 1
    assert reloaded.watch[0].sku == "314206561604"
    assert reloaded.watch[0].sizes == ["9", "10"]
    assert reloaded.notifiers[0]["type"] == "discord"
    # File is valid JSON on disk.
    json.load(open(path))


def test_build_status_marks_pending_before_first_check(tmp_path):
    cfg = _config(tmp_path, [WatchedProduct(sku="314206561604", name="AJ1", retailer="footlocker")])
    status = build_status(cfg)
    assert status["watched_count"] == 1
    p = status["products"][0]
    assert p["pending"] is True
    assert p["name"] == "AJ1"
    # A URL is synthesized from the retailer so the row links somewhere.
    assert "footlocker.com" in p["url"]
