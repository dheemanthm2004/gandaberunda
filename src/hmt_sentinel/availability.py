"""Availability classification logic and safety rules."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from bs4 import BeautifulSoup

from hmt_sentinel.models import AvailabilityState

logger = logging.getLogger(__name__)

# Out-of-stock textual cues
OOS_REGEX = re.compile(
    r"\b(out\s+of\s+stock|sold\s+out|currently\s+unavailable|stock\s+out|not\s+in\s+stock)\b",
    re.IGNORECASE,
)

# Coming-soon textual cues
COMING_SOON_REGEX = re.compile(
    r"\b(coming\s+soon|upcoming|launching\s+soon|pre[- ]?order|pre[- ]?sale)\b",
    re.IGNORECASE,
)

# Explicit purchasable cues (active Add to Cart or Buy Now)
ADD_TO_CART_REGEX = re.compile(
    r"\b(add\s+to\s+cart|buy\s+now|add\s+to\s+bag|purchase)\b",
    re.IGNORECASE,
)

# Notify me cues (explicitly not in stock)
NOTIFY_ME_REGEX = re.compile(
    r"\b(notify\s+me|notify\s+when\s+available|email\s+when\s+available)\b",
    re.IGNORECASE,
)


@dataclass
class AvailabilityResult:
    state: AvailabilityState
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


def classify_from_flags(
    *,
    in_stock: Optional[bool] = None,
    is_buyable: Optional[bool] = None,
    current_stock: Optional[int] = None,
    is_coming_soon: Optional[bool] = None,
    raw_status: Optional[str] = None,
) -> AvailabilityResult:
    """Classify availability from structured API flags (e.g. Amazon SmartBiz or JSON APIs).
    
    Safety rules:
    - If is_buyable is explicitly False -> OUT_OF_STOCK.
    - If current_stock == 0 -> OUT_OF_STOCK.
    - If is_coming_soon is True -> COMING_SOON.
    - If in_stock is True AND is_buyable is True (or not False) AND current_stock != 0 -> IN_STOCK.
    - If in_stock is False -> OUT_OF_STOCK.
    - Conflicting or missing information -> UNKNOWN.
    """
    if is_coming_soon:
        return AvailabilityResult(AvailabilityState.COMING_SOON, "flag:is_coming_soon=True")

    if raw_status:
        s = raw_status.strip().lower()
        if "coming" in s or "soon" in s:
            return AvailabilityResult(AvailabilityState.COMING_SOON, f"flag:raw_status={raw_status}")
        if "out" in s or "sold" in s:
            return AvailabilityResult(AvailabilityState.OUT_OF_STOCK, f"flag:raw_status={raw_status}")

    if is_buyable is False:
        return AvailabilityResult(AvailabilityState.OUT_OF_STOCK, "flag:is_buyable=False")

    if current_stock is not None:
        if current_stock <= 0:
            return AvailabilityResult(AvailabilityState.OUT_OF_STOCK, f"flag:current_stock={current_stock}")

    if in_stock is False:
        return AvailabilityResult(AvailabilityState.OUT_OF_STOCK, "flag:in_stock=False")

    if in_stock is True and is_buyable is True:
        return AvailabilityResult(AvailabilityState.IN_STOCK, "flag:in_stock=True,is_buyable=True")

    if in_stock is True and is_buyable is None and (current_stock is None or current_stock > 0):
        return AvailabilityResult(AvailabilityState.IN_STOCK, "flag:in_stock=True")

    return AvailabilityResult(AvailabilityState.UNKNOWN, "flag:insufficient_signals")


def classify_from_html(soup: BeautifulSoup, context: str = "detail") -> AvailabilityResult:
    """Classify availability conservatively from HTML page or snippet.
    
    Safety rules:
    - Look for explicit 'Coming Soon' -> COMING_SOON.
    - Look for explicit 'Out of Stock' or 'Sold Out' -> OUT_OF_STOCK.
    - Look for 'Notify Me' without purchasable button -> OUT_OF_STOCK.
    - Disabled purchase buttons -> OUT_OF_STOCK.
    - Enabled 'Add to Cart' or 'Buy Now' with no conflicting OOS indicators -> IN_STOCK.
    - Conflicting signals or no clear signals -> UNKNOWN.
    """
    # Create a working copy so we don't mutate caller's soup
    working_soup = BeautifulSoup(str(soup), "lxml")

    # Remove extraneous site chrome that might contain unrelated cart buttons (e.g. quick-view modals, headers, footers)
    for extraneous in working_soup.select(".modal, .modal-dialog, header, footer, #quick_view, #product_view"):
        extraneous.decompose()

    text_content = working_soup.get_text(separator=" ", strip=True)

    has_coming_soon = bool(COMING_SOON_REGEX.search(text_content))
    has_oos = bool(OOS_REGEX.search(text_content))
    has_notify = bool(NOTIFY_ME_REGEX.search(text_content))

    # Check for specific known containers on HMT sites:
    # 1. <div class="outofstock"> ...
    oos_div = working_soup.select_one(".outofstock")
    if oos_div:
        div_text = oos_div.get_text(strip=True)
        if COMING_SOON_REGEX.search(div_text):
            return AvailabilityResult(AvailabilityState.COMING_SOON, f"{context}:outofstock_div_coming_soon")
        if OOS_REGEX.search(div_text):
            return AvailabilityResult(AvailabilityState.OUT_OF_STOCK, f"{context}:outofstock_div_oos")
        return AvailabilityResult(AvailabilityState.OUT_OF_STOCK, f"{context}:outofstock_div_present")

    # 2. Check all buttons for purchasability and disabled states
    buttons = working_soup.find_all(["button", "a", "input"])
    cart_buttons_enabled = []
    cart_buttons_disabled = []
    explicit_oos_button = False

    for btn in buttons:
        btn_text = btn.get_text(separator=" ", strip=True) if btn.name != "input" else (btn.get("value") or "")
        btn_classes = " ".join(btn.get("class", []))
        btn_disabled = btn.has_attr("disabled") or "disabled" in btn_classes.lower()

        if OOS_REGEX.search(btn_text):
            explicit_oos_button = True

        if ADD_TO_CART_REGEX.search(btn_text):
            if btn_disabled:
                cart_buttons_disabled.append(btn_text)
            else:
                cart_buttons_enabled.append(btn_text)

    if explicit_oos_button:
        return AvailabilityResult(AvailabilityState.OUT_OF_STOCK, f"{context}:explicit_oos_button")

    # If Coming Soon text is prominent
    if has_coming_soon and not cart_buttons_enabled:
        return AvailabilityResult(AvailabilityState.COMING_SOON, f"{context}:coming_soon_text")

    # If OOS or Notify Me text is present and there are NO enabled cart buttons
    if (has_oos or has_notify or cart_buttons_disabled) and not cart_buttons_enabled:
        reason = f"{context}:" + (
            "oos_text" if has_oos else ("cart_disabled" if cart_buttons_disabled else "notify_me")
        )
        return AvailabilityResult(AvailabilityState.OUT_OF_STOCK, reason)

    # If we have enabled cart buttons:
    if cart_buttons_enabled:
        # Check for conflict: if OOS or Coming Soon text is also present on the page
        if has_oos:
            return AvailabilityResult(
                AvailabilityState.UNKNOWN,
                f"{context}:conflict_cart_enabled_and_oos_text",
            )
        if has_coming_soon:
            return AvailabilityResult(
                AvailabilityState.UNKNOWN,
                f"{context}:conflict_cart_enabled_and_coming_soon_text",
            )
        return AvailabilityResult(
            AvailabilityState.IN_STOCK,
            f"{context}:cart_button_enabled",
            {"button": cart_buttons_enabled[0]},
        )

    # If notify me only
    if has_notify:
        return AvailabilityResult(AvailabilityState.OUT_OF_STOCK, f"{context}:notify_me_only")

    # No clear signal
    return AvailabilityResult(AvailabilityState.UNKNOWN, f"{context}:no_conclusive_evidence")

