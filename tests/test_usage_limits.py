# Tests for usage_limits.py, using its in-memory mode (db=None), so no
# Firebase connection is needed.

import pytest

import usage_limits


# A "fixture": pytest runs this before every test in this file. autouse=True
# applies it automatically, so each test starts with fresh, empty counts.
@pytest.fixture(autouse=True)
def fresh_counts():
    usage_limits._memory.update({"day": None, "spend": 0.0, "visitors": {}})


def test_visitor_id_never_contains_the_ip_address():
    vid = usage_limits.visitor_id("203.0.113.7")
    assert "203.0.113.7" not in vid
    assert vid == usage_limits.visitor_id("203.0.113.7")
    assert vid != usage_limits.visitor_id("203.0.113.8")


def test_local_development_has_no_visitor_id():
    assert usage_limits.visitor_id(None) is None


def test_visitor_is_blocked_after_daily_reply_limit(monkeypatch):
    monkeypatch.setattr(usage_limits, "VISITOR_DAILY_REPLY_LIMIT", 2)
    v = usage_limits.visitor_id("203.0.113.7")
    assert usage_limits.check_limits(None, v) is None
    usage_limits.record_usage(None, v, 0.001)
    usage_limits.record_usage(None, v, 0.001)
    assert usage_limits.check_limits(None, v) == usage_limits.VISITOR_LIMIT_MESSAGE
    # A different visitor is unaffected.
    assert usage_limits.check_limits(None, usage_limits.visitor_id("198.51.100.1")) is None


def test_everyone_is_paused_once_daily_spend_limit_is_reached(monkeypatch):
    monkeypatch.setattr(usage_limits, "DAILY_SPEND_LIMIT_USD", 0.01)
    usage_limits.record_usage(None, usage_limits.visitor_id("203.0.113.7"), 0.02)
    other = usage_limits.visitor_id("198.51.100.1")
    assert usage_limits.check_limits(None, other) == usage_limits.DAILY_LIMIT_MESSAGE


def test_counts_reset_on_a_new_day(monkeypatch):
    monkeypatch.setattr(usage_limits, "DAILY_SPEND_LIMIT_USD", 0.01)
    usage_limits.record_usage(None, None, 0.02)
    monkeypatch.setattr(usage_limits, "today", lambda: "2099-01-01")
    assert usage_limits.check_limits(None, None) is None
