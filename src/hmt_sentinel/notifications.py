"""Telegram notification service with retries, deduplication, and timezone handling."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from hmt_sentinel.models import Product, utcnow
from hmt_sentinel.state import TransitionEvent

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    from datetime import timedelta
    KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30))
TELEGRAM_API_BASE = "https://api.telegram.org"


def format_restock_message(product: Product, detected_at: Optional[datetime] = None) -> str:
    """Format a restock notification message following the project specification."""
    dt = detected_at or product.last_transition or utcnow()
    kolkata_time = dt.astimezone(KOLKATA_TZ).strftime("%d %b %Y, %I:%M:%S %p IST")

    lines = [
        "🎉 HMT GANDABERUNDA RESTOCK DETECTED",
        "",
        f"Product: {product.name}",
    ]

    if product.model_ref:
        lines.append(f"Model: {product.model_ref}")

    if product.price:
        lines.append(f"Price: {product.price}")

    lines.extend([
        f"Website: {product.domain}",
        f"Status: {product.availability.value}",
        f"Detected at: {kolkata_time}",
        f"Buy now: {product.url}",
    ])

    return "\n".join(lines)


def format_test_message() -> str:
    """Format a Telegram configuration verification message."""
    kolkata_time = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).strftime("%d %b %Y, %I:%M:%S %p IST")
    return (
        "✅ HMT GANDABERUNDA SENTINEL — TEST NOTIFICATION\n\n"
        "Your Telegram bot and chat configuration is active and working.\n"
        f"Timestamp: {kolkata_time}\n"
        "Status: System ready to monitor hmtwatches.store and hmtwatches.in"
    )


def format_failure_message(error_summary: str) -> str:
    """Format a monitoring failure diagnostic alert."""
    kolkata_time = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).strftime("%d %b %Y, %I:%M:%S %p IST")
    return (
        "⚠️ HMT SENTINEL MONITORING FAILURE\n\n"
        f"Time: {kolkata_time}\n"
        f"Summary:\n{error_summary}\n\n"
        "Check workflow logs for details."
    )


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        dry_run: bool = False,
        timeout: int = 20,
        max_retries: int = 3,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.dry_run = dry_run
        self.timeout = timeout
        self.max_retries = max_retries

    def send_message(self, text: str) -> bool:
        """Send a message via Telegram Bot API with bounded retries and exponential backoff."""
        if self.dry_run:
            logger.info("[DRY-RUN] Would send Telegram alert to chat %s:\n%s", self.chat_id, text)
            return True

        if not self.bot_token or not self.chat_id:
            logger.error("Cannot send Telegram message: bot_token or chat_id is missing")
            return False

        url = f"{TELEGRAM_API_BASE}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": False,
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        logger.info("Telegram notification delivered successfully (attempt %d)", attempt)
                        return True
                    else:
                        logger.error("Telegram API returned ok=False: %s", data.get("description"))
                elif resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    logger.warning("Telegram rate-limited (429). Waiting %ds", retry_after)
                    time.sleep(retry_after)
                else:
                    logger.warning("Telegram HTTP %d (attempt %d/%d): %s", resp.status_code, attempt, self.max_retries, resp.text)
            except requests.RequestException as exc:
                logger.warning("Telegram request exception (attempt %d/%d): %s", attempt, self.max_retries, exc)

            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 8))

        logger.error("Failed to send Telegram notification after %d attempts", self.max_retries)
        return False

    def notify_restock(self, event: TransitionEvent) -> bool:
        """Deliver restock alert for a confirmed transition event."""
        if not event.should_notify:
            return False

        msg = format_restock_message(event.product, event.detected_at)
        success = self.send_message(msg)
        if success:
            event.product.last_notified = utcnow()
        return success

    def send_test_notification(self) -> bool:
        """Send a test notification to verify credentials."""
        msg = format_test_message()
        return self.send_message(msg)

    def notify_monitoring_failure(self, error_summary: str) -> bool:
        """Send an optional failure alert when monitoring encounters critical errors."""
        msg = format_failure_message(error_summary)
        return self.send_message(msg)
