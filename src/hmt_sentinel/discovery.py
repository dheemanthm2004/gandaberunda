"""Dynamic product discovery coordinator."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from hmt_sentinel.adapters.base import BaseAdapter
from hmt_sentinel.adapters.hmt_in import HMTInAdapter
from hmt_sentinel.adapters.hmt_store import HMTStoreAdapter
from hmt_sentinel.models import Product

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryReport:
    domain: str
    success: bool
    products: list[Product] = field(default_factory=list)
    error: Optional[str] = None


class DiscoveryService:
    def __init__(
        self,
        store_adapter: Optional[BaseAdapter] = None,
        in_adapter: Optional[BaseAdapter] = None,
    ) -> None:
        self.store_adapter = store_adapter or HMTStoreAdapter()
        self.in_adapter = in_adapter or HMTInAdapter()

    def discover_store(self) -> DiscoveryReport:
        """Run dynamic discovery on primary website (hmtwatches.store)."""
        logger.info("Executing discovery for %s", self.store_adapter.domain)
        try:
            prods = self.store_adapter.discover()
            err = self.store_adapter.last_error
            # If adapter reported an error and found 0 products, treat as failed
            success = not (err and len(prods) == 0)
            return DiscoveryReport(domain=self.store_adapter.domain, success=success, products=prods, error=err)
        except Exception as exc:
            logger.exception("Unexpected exception during store discovery: %s", exc)
            return DiscoveryReport(domain=self.store_adapter.domain, success=False, products=[], error=str(exc))

    def discover_in(self) -> DiscoveryReport:
        """Run dynamic discovery on secondary website (hmtwatches.in)."""
        logger.info("Executing discovery for %s", self.in_adapter.domain)
        try:
            prods = self.in_adapter.discover()
            err = self.in_adapter.last_error
            success = not (err and len(prods) == 0)
            return DiscoveryReport(domain=self.in_adapter.domain, success=success, products=prods, error=err)
        except Exception as exc:
            logger.exception("Unexpected exception during .in discovery: %s", exc)
            return DiscoveryReport(domain=self.in_adapter.domain, success=False, products=[], error=str(exc))

    def discover_all(self, enable_store: bool = True, enable_in: bool = True) -> dict[str, DiscoveryReport]:
        """Discover products across all enabled domains, prioritizing .store first."""
        results: dict[str, DiscoveryReport] = {}
        if enable_store:
            results["hmtwatches.store"] = self.discover_store()
        if enable_in:
            results["hmtwatches.in"] = self.discover_in()
        return results
