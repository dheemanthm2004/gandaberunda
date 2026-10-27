"""Tests for Telegram notifications, formatting, retries, and deduplication."""
from datetime import datetime, timezone
import pytest
import responses

from hmt_sentinel.models import AvailabilityState, Product
from hmt_sentinel.notifications import (
    TelegramNotifier,
    format_failure_message,
    format_restock_message,
    format_test_message,
)
from hmt_sentinel.state import TransitionEvent, TransitionType


def test_format_restock_message_complete():
    dt = datetime(2026, 10, 27, 10, 30, 0, tzinfo=timezone.utc)
    prod = Product(
        domain="hmtwatches.store",
        product_id="sku-123",
        name="HMT Women's Gandaberunda JLGG - 01 White",
        url="https://www.hmtwatches.store/product/sku-123",
        price="₹2599",
        model_ref="JLGG 01",
        availability=AvailabilityState.IN_STOCK,
        last_transition=dt,
    )
    msg = format_restock_message(prod, dt)

    assert "🎉 HMT GANDABERUNDA RESTOCK DETECTED" in msg
    assert "Product: HMT Women's Gandaberunda JLGG - 01 White" in msg
    assert "Model: JLGG 01" in msg
    assert "Price: ₹2599" in msg
    assert "Website: hmtwatches.store" in msg
    assert "Status: IN_STOCK" in msg
    assert "Detected at: 27 Oct 2026, 04:00:00 PM IST" in msg
    assert "Buy now: https://www.hmtwatches.store/product/sku-123" in msg


def test_format_restock_message_missing_optional_fields():
    dt = datetime(2026, 10, 27, 10, 30, 0, tzinfo=timezone.utc)
    prod = Product(
        domain="hmtwatches.in",
        product_id="1216",
        name="HMT Gandaberunda",
        url="https://www.hmtwatches.in/product_overview?id=1216",
        price=None,       # Missing price
        model_ref=None,   # Missing model
        availability=AvailabilityState.IN_STOCK,
        last_transition=dt,
    )
    msg = format_restock_message(prod, dt)

    assert "Product: HMT Gandaberunda" in msg
    assert "Model:" not in msg
    assert "Price:" not in msg
    assert "Buy now: https://www.hmtwatches.in/product_overview?id=1216" in msg


def test_format_test_and_failure_messages():
    test_msg = format_test_message()
    assert "TEST NOTIFICATION" in test_msg
    assert "ready to monitor" in test_msg

    fail_msg = format_failure_message("Discovery failed on hmtwatches.store")
    assert "MONITORING FAILURE" in fail_msg
    assert "Discovery failed on hmtwatches.store" in fail_msg


@responses.activate
def test_telegram_send_success():
    responses.add(
        responses.POST,
        "https://api.telegram.org/bot123456:ABC/sendMessage",
        json={"ok": True, "result": {"message_id": 999}},
        status=200,
    )

    notifier = TelegramNotifier(bot_token="123456:ABC", chat_id="chat99", dry_run=False)
    prod = Product(
        domain="hmtwatches.store",
        product_id="sku-1",
        name="HMT Gandaberunda",
        url="https://www.hmtwatches.store/product/sku-1",
        availability=AvailabilityState.IN_STOCK,
    )
    event = TransitionEvent(
        product=prod,
        transition_type=TransitionType.RESTOCKED,
        previous_state=AvailabilityState.OUT_OF_STOCK,
        current_state=AvailabilityState.IN_STOCK,
        should_notify=True,
    )
    assert prod.last_notified is None
    success = notifier.notify_restock(event)
    assert success is True
    assert prod.last_notified is not None


@responses.activate
def test_telegram_send_failure_and_retries():
    # 3 failures -> returns False
    responses.add(
        responses.POST,
        "https://api.telegram.org/bot123456:ABC/sendMessage",
        status=500,
    )
    responses.add(
        responses.POST,
        "https://api.telegram.org/bot123456:ABC/sendMessage",
        status=502,
    )
    responses.add(
        responses.POST,
        "https://api.telegram.org/bot123456:ABC/sendMessage",
        status=503,
    )

    notifier = TelegramNotifier(bot_token="123456:ABC", chat_id="chat99", dry_run=False, max_retries=3)
    prod = Product(
        domain="hmtwatches.store",
        product_id="sku-1",
        name="HMT Gandaberunda",
        url="https://www.hmtwatches.store/product/sku-1",
        availability=AvailabilityState.IN_STOCK,
    )
    event = TransitionEvent(
        product=prod,
        transition_type=TransitionType.RESTOCKED,
        previous_state=AvailabilityState.OUT_OF_STOCK,
        current_state=AvailabilityState.IN_STOCK,
        should_notify=True,
    )
    success = notifier.notify_restock(event)
    assert success is False
    # Not delivered, so last_notified must NOT be set
    assert prod.last_notified is None


def test_telegram_dry_run_does_not_call_api():
    # In dry run mode, no HTTP calls should be made
    notifier = TelegramNotifier(bot_token="123456:ABC", chat_id="chat99", dry_run=True)
    success = notifier.send_message("Test message")
    assert success is True


def test_telegram_send_test_notification(mocker):
    notifier = TelegramNotifier(bot_token="123456:ABC", chat_id="chat99", dry_run=False)
    mocker.patch.object(notifier, "send_message", return_value=True)
    res = notifier.send_test_notification()
    assert res is True
    assert notifier.send_message.called


def test_telegram_missing_credentials():
    notifier = TelegramNotifier(bot_token="", chat_id="", dry_run=False)
    assert notifier.send_message("Hello") is False
