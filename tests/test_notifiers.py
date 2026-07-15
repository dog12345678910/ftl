"""Tests for notifier construction and payload formatting (no network)."""

import unittest.mock as m

import pytest

from footlocker_monitor.notifiers import build_notifiers
from footlocker_monitor.notifiers.webhook import SlackNotifier, WebhookNotifier
from footlocker_monitor.state import RestockEvent


def _event(**kw):
    base = dict(
        sku="1", name="AJ1", url="http://x", newly_available_sizes=["9"],
        price="$150", image=None, first_seen=False, kind="restock",
    )
    base.update(kw)
    return RestockEvent(**base)


def test_build_notifiers_registry():
    ns = build_notifiers([
        {"type": "console"},
        {"type": "webhook", "url": "http://example.com/hook"},
    ])
    assert len(ns) == 2
    assert isinstance(ns[1], WebhookNotifier)


def test_build_notifiers_unknown_type():
    with pytest.raises(ValueError):
        build_notifiers([{"type": "smoke-signal"}])


def test_build_notifiers_missing_required_option():
    # Missing 'webhook_url' surfaces as a TypeError (missing arg); either way
    # construction must fail loudly rather than silently no-op.
    with pytest.raises((ValueError, TypeError)):
        build_notifiers([{"type": "discord"}])


def test_webhook_payload_shape():
    n = WebhookNotifier(url="http://example.com/hook")
    with m.patch("footlocker_monitor.notifiers.webhook.requests.post") as post:
        post.return_value = m.Mock(status_code=200)
        n.notify(_event())
    payload = post.call_args.kwargs["json"]
    assert payload["kind"] == "restock"
    assert payload["sku"] == "1"
    assert payload["sizes"] == ["9"]
    assert "RESTOCK" in payload["title"]


def test_slack_payload_is_text():
    n = SlackNotifier(url="http://hooks.slack.com/x")
    with m.patch("footlocker_monitor.notifiers.webhook.requests.post") as post:
        post.return_value = m.Mock(status_code=200)
        n.notify(_event(kind="price_drop", previous_price="$200"))
    payload = post.call_args.kwargs["json"]
    assert set(payload) == {"text"}
    assert "PRICE DROP" in payload["text"]
    assert "$200 → $150" in payload["text"]


def test_webhook_swallows_network_error():
    import requests

    n = WebhookNotifier(url="http://example.com/hook")
    with m.patch(
        "footlocker_monitor.notifiers.webhook.requests.post",
        side_effect=requests.ConnectionError("boom"),
    ):
        n.notify(_event())  # must not raise
