"""Monitoring engine and orchestrator."""
from __future__ import annotations

import logging
from typing import Optional

from hmt_sentinel.adapters.base import BaseAdapter
from hmt_sentinel.adapters.hmt_in import HMTInAdapter
from hmt_sentinel.adapters.hmt_store import HMTStoreAdapter
from hmt_sentinel.config import Config, get_config
from hmt_sentinel.models import AvailabilityState, Product, RunSummary, utcnow
from hmt_sentinel.notifications import TelegramNotifier
from hmt_sentinel.state import StateStore, TransitionEvent

logger = logging.getLogger(__name__)


class MonitoringEngine:
    def __init__(
        self,
        config: Optional[Config] = None,
        state_store: Optional[StateStore] = None,
        notifier: Optional[TelegramNotifier] = None,
        store_adapter: Optional[BaseAdapter] = None,
        in_adapter: Optional[BaseAdapter] = None,
    ) -> None:
        self.config = config or get_config()
        self.state_store = state_store or StateStore(self.config.state_file)
        self.notifier = notifier or TelegramNotifier(
            bot_token=self.config.telegram_bot_token,
            chat_id=self.config.telegram_chat_id,
            dry_run=self.config.dry_run,
            timeout=self.config.request_timeout,
            max_retries=self.config.max_retries,
        )
        self.store_adapter = store_adapter or HMTStoreAdapter()
        self.in_adapter = in_adapter or HMTInAdapter()

    def run(self) -> RunSummary:
        """Execute a complete monitoring cycle adhering to website priority and error isolation."""
        summary = RunSummary(start_time=utcnow())
        logger.info("=== Starting Monitoring Cycle ===")

        # Track products to notify
        pending_notifications: list[TransitionEvent] = []

        # Phase 1: Primary Website (hmtwatches.store)
        if self.config.enable_store:
            logger.info("--- Monitoring Primary Domain: %s ---", self.store_adapter.domain)
            try:
                self._monitor_domain(
                    adapter=self.store_adapter,
                    summary=summary,
                    is_store=True,
                    pending_notifications=pending_notifications,
                )
            except Exception as exc:
                err_msg = f"Fatal error during {self.store_adapter.domain} monitoring: {exc}"
                logger.exception(err_msg)
                summary.errors.append(err_msg)
                summary.store_discovery_ok = False
        else:
            logger.info("Primary domain %s is disabled in configuration", self.store_adapter.domain)

        # Save state after store checks so store results are safely preserved
        try:
            self.state_store.save()
        except Exception as exc:
            summary.errors.append(f"Failed to save state after store run: {exc}")

        # Phase 2: Secondary Website (hmtwatches.in)
        if self.config.enable_in:
            logger.info("--- Monitoring Secondary Domain: %s ---", self.in_adapter.domain)
            try:
                self._monitor_domain(
                    adapter=self.in_adapter,
                    summary=summary,
                    is_store=False,
                    pending_notifications=pending_notifications,
                )
            except Exception as exc:
                err_msg = f"Fatal error during {self.in_adapter.domain} monitoring: {exc}"
                logger.exception(err_msg)
                summary.errors.append(err_msg)
                summary.in_discovery_ok = False
        else:
            logger.info("Secondary domain %s is disabled in configuration", self.in_adapter.domain)

        # Save state after .in checks
        try:
            self.state_store.save()
        except Exception as exc:
            summary.errors.append(f"Failed to save state after .in run: {exc}")

        # Phase 3: Deliver Notifications
        for event in pending_notifications:
            logger.info(
                "Delivering restock alert for %s (%s)",
                event.product.name,
                event.product.url,
            )
            delivered = self.notifier.notify_restock(event)
            if delivered:
                summary.notifications_sent += 1
            else:
                summary.notifications_failed += 1

        # Re-save state to record product.last_notified timestamps
        if summary.notifications_sent > 0:
            try:
                self.state_store.save()
            except Exception as exc:
                summary.errors.append(f"Failed to save state after notification delivery: {exc}")

        summary.end_time = utcnow()
        duration = (summary.end_time - summary.start_time).total_seconds()

        # Phase 4: Handle Failure Alert if enabled
        if summary.errors and self.config.notify_on_failure:
            try:
                self.notifier.notify_monitoring_failure("\n".join(summary.errors))
            except Exception as exc:
                logger.warning("Failed to send monitoring failure notification: %s", exc)

        logger.info(
            "=== Monitoring Cycle Finished in %.2fs (Found: store=%d, in=%d | Checked: store=%d, in=%d | Stock: in=%d, oos=%d, coming_soon=%d, unknown=%d | Alerts: sent=%d, failed=%d) ===",
            duration,
            summary.store_products_found,
            summary.in_products_found,
            summary.store_checked,
            summary.in_checked,
            summary.in_stock,
            summary.out_of_stock,
            summary.coming_soon,
            summary.unknown,
            summary.notifications_sent,
            summary.notifications_failed,
        )

        return summary

    def _monitor_domain(
        self,
        adapter: BaseAdapter,
        summary: RunSummary,
        is_store: bool,
        pending_notifications: list[TransitionEvent],
    ) -> None:
        """Run discovery, detail checking, and state updates for a single domain."""
        domain = adapter.domain
        discovered_products: list[Product] = []
        discovery_ok = True

        try:
            discovered_products = adapter.discover()
            if adapter.last_error and len(discovered_products) == 0:
                discovery_ok = False
                summary.errors.append(f"[{domain}] Discovery failed: {adapter.last_error}")
        except Exception as exc:
            discovery_ok = False
            summary.errors.append(f"[{domain}] Exception during discovery: {exc}")
            logger.exception("[%s] Discovery exception: %s", domain, exc)

        if is_store:
            summary.store_discovery_ok = discovery_ok
            summary.store_products_found = len(discovered_products)
        else:
            summary.in_discovery_ok = discovery_ok
            summary.in_products_found = len(discovered_products)

        # Merge with existing products in state for this domain
        # If discovery succeeds, also mark any missing products
        active_ids = {p.product_id for p in discovered_products}
        products_to_check: dict[str, Product] = {}

        # First add all newly discovered
        for p in discovered_products:
            products_to_check[p.product_id] = p

        # If discovery was successful, mark products not in active_ids as missing
        if discovery_ok and active_ids:
            self.state_store.mark_missing(domain, active_ids)

        # Also re-check existing known products from state that weren't discovered this run
        for key, p in self.state_store.products.items():
            if p.domain == domain and p.product_id not in products_to_check:
                products_to_check[p.product_id] = p

        # Now check availability of each product
        for pid, prod in products_to_check.items():
            if is_store:
                summary.store_checked += 1
            else:
                summary.in_checked += 1

            try:
                # If product already has a verified state from discovery and was just discovered,
                # we re-check if unknown, price missing, or if title is truncated (e.g. ends with '..')
                if prod.availability == AvailabilityState.UNKNOWN or prod.price is None or prod.name.endswith(".."):
                    checked_prod = adapter.check_product(prod)
                else:
                    checked_prod = prod
            except Exception as exc:
                logger.warning("[%s] Failed to check product %s: %s", domain, prod.url, exc)
                prod.availability = AvailabilityState.UNKNOWN
                prod.availability_reason = f"check_exception:{exc}"
                checked_prod = prod

            # Update counters
            if checked_prod.availability == AvailabilityState.IN_STOCK:
                summary.in_stock += 1
            elif checked_prod.availability == AvailabilityState.OUT_OF_STOCK:
                summary.out_of_stock += 1
            elif checked_prod.availability == AvailabilityState.COMING_SOON:
                summary.coming_soon += 1
            else:
                summary.unknown += 1

            # Update state store and collect any transition events
            updated_prod, event = self.state_store.register_or_update(checked_prod)
            if event and event.should_notify:
                pending_notifications.append(event)

