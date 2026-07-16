"""Tests for the Twilio SMS notifier (no network)."""

import unittest.mock as m

import pytest

from footlocker_monitor.notifiers import build_notifiers
from footlocker_monitor.notifiers.sms import TwilioSMSNotifier
from footlocker_monitor.state import RestockEvent


def _event():
    return RestockEvent(sku="1", name="AJ1", url="http://x",
                        newly_available_sizes=["9"], price="$180", kind="restock")


def test_sms_requires_credentials():
    with pytest.raises(ValueError):
        TwilioSMSNotifier(account_sid="", auth_token="t", from_number="+1", to="+2")


def test_sms_posts_to_twilio_with_auth():
    n = TwilioSMSNotifier(account_sid="ACxxx", auth_token="tok",
                          from_number="+15005550006", to=["+1234", "+5678"])
    with m.patch("footlocker_monitor.notifiers.sms.requests.post") as post:
        post.return_value = m.Mock(status_code=201)
        n.notify(_event())

    assert post.call_count == 2  # one per recipient
    call = post.call_args_list[0]
    assert "ACxxx/Messages.json" in call.args[0]
    assert call.kwargs["auth"] == ("ACxxx", "tok")
    assert call.kwargs["data"]["From"] == "+15005550006"
    assert "RESTOCK" in call.kwargs["data"]["Body"]


def test_sms_registered_in_builder():
    ns = build_notifiers([{
        "type": "sms", "account_sid": "AC", "auth_token": "t",
        "from_number": "+1", "to": "+2",
    }])
    assert isinstance(ns[0], TwilioSMSNotifier)
