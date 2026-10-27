"""State management, transition detection, and atomic persistence."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from hmt_sentinel.models import AvailabilityState, Product, utcnow

logger = logging.getLogger(__name__)

CURRENT_STATE_SCHEMA_VERSION = 1


class TransitionType:
    INITIAL_IN_STOCK = "INITIAL_IN_STOCK"
    RESTOCKED = "RESTOCKED"
    NOW_OUT_OF_STOCK = "NOW_OUT_OF_STOCK"
    NOW_COMING_SOON = "NOW_COMING_SOON"
    NO_CHANGE = "NO_CHANGE"
    BECAME_UNKNOWN = "BECAME_UNKNOWN"


@dataclass
class TransitionEvent:
    product: Product
    transition_type: str
    previous_state: Optional[AvailabilityState]
    current_state: AvailabilityState
    should_notify: bool
    detected_at: datetime = field(default_factory=utcnow)


class StateStore:
    def __init__(self, file_path: Path | str = "state.json") -> None:
        self.file_path = Path(file_path)
        self.backup_path = self.file_path.with_suffix(".json.bak")
        self.products: dict[str, Product] = {}
        self.version = CURRENT_STATE_SCHEMA_VERSION
        self.last_run_timestamp: Optional[datetime] = None
        self.load()

    def load(self) -> None:
        """Load state from file, falling back to backup or empty state if corrupted."""
        self.products = {}
        if not self.file_path.exists():
            if self.backup_path.exists():
                logger.warning("Primary state file %s missing, attempting backup %s", self.file_path, self.backup_path)
                self._load_from_path(self.backup_path)
            return

        success = self._load_from_path(self.file_path)
        if not success and self.backup_path.exists():
            logger.warning("Primary state file corrupted, attempting recovery from backup %s", self.backup_path)
            self._load_from_path(self.backup_path)

    def _load_from_path(self, path: Path) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.version = data.get("version", CURRENT_STATE_SCHEMA_VERSION)
            ts_str = data.get("last_run_timestamp")
            if ts_str:
                try:
                    self.last_run_timestamp = datetime.fromisoformat(ts_str)
                except ValueError:
                    self.last_run_timestamp = None

            raw_prods = data.get("products", {})
            for key, p_dict in raw_prods.items():
                try:
                    prod = Product.from_dict(p_dict)
                    self.products[prod.key] = prod
                except Exception as exc:
                    logger.warning("Failed to deserialize product %s: %s", key, exc)
            logger.info("Loaded %d products from state file (%s)", len(self.products), path)
            return True
        except Exception as exc:
            logger.error("Failed to load state from %s: %s", path, exc)
            return False

    def save(self) -> None:
        """Atomically persist state to disk and maintain a backup."""
        self.last_run_timestamp = utcnow()
        data = {
            "version": self.version,
            "last_run_timestamp": self.last_run_timestamp.isoformat(),
            "products": {k: p.to_dict() for k, p in self.products.items()},
        }
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.file_path.with_suffix(".json.tmp")

        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            # Create backup before replacing primary
            if self.file_path.exists():
                try:
                    with open(self.file_path, "rb") as src, open(self.backup_path, "wb") as dst:
                        dst.write(src.read())
                except Exception as exc:
                    logger.warning("Failed to write state backup file: %s", exc)

            os.replace(temp_file, self.file_path)
            logger.info("Saved %d products to state file (%s)", len(self.products), self.file_path)
        except Exception as exc:
            logger.exception("Failed to write state file %s: %s", self.file_path, exc)
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise

    def get_product(self, domain: str, product_id: str) -> Optional[Product]:
        key = f"{domain}::{product_id}"
        return self.products.get(key)

    def register_or_update(
        self,
        new_obs: Product,
    ) -> tuple[Product, Optional[TransitionEvent]]:
        """Register or update a product observation, evaluating state machine transitions.
        
        Returns:
            (updated_product, transition_event_if_any)
        """
        now = utcnow()
        existing = self.products.get(new_obs.key)

        if existing is None:
            # First time seeing this product
            new_obs.first_seen = new_obs.first_seen or now
            new_obs.last_checked = now
            if new_obs.availability != AvailabilityState.UNKNOWN:
                new_obs.last_successful_check = now
                new_obs.last_reliable_availability = new_obs.availability

            self.products[new_obs.key] = new_obs

            # Initial in-stock alert
            if new_obs.availability == AvailabilityState.IN_STOCK:
                new_obs.last_transition = now
                event = TransitionEvent(
                    product=new_obs,
                    transition_type=TransitionType.INITIAL_IN_STOCK,
                    previous_state=None,
                    current_state=AvailabilityState.IN_STOCK,
                    should_notify=True,
                    detected_at=now,
                )
                return new_obs, event

            return new_obs, None

        # Existing product
        existing.last_checked = now
        existing.missing_from_listing = False

        # Update metadata if available
        if new_obs.name and not new_obs.name.endswith(".."):
            existing.name = new_obs.name
        if new_obs.price:
            existing.price = new_obs.price
        if new_obs.model_ref:
            existing.model_ref = new_obs.model_ref
        if new_obs.url:
            existing.url = new_obs.url

        prev_state = existing.availability
        prev_reliable = existing.last_reliable_availability
        curr_state = new_obs.availability

        if curr_state != AvailabilityState.UNKNOWN:
            existing.last_successful_check = now
            existing.availability = curr_state
            existing.availability_reason = new_obs.availability_reason
            existing.last_reliable_availability = curr_state
        else:
            # Current check failed / unknown: keep previous reliable state untouched!
            existing.availability = AvailabilityState.UNKNOWN
            existing.availability_reason = new_obs.availability_reason
            # Do NOT fire alert on UNKNOWN
            return existing, None

        # Evaluate transitions between reliable states
        if prev_reliable is None:
            # Previous was only ever UNKNOWN
            if curr_state == AvailabilityState.IN_STOCK:
                existing.last_transition = now
                event = TransitionEvent(
                    product=existing,
                    transition_type=TransitionType.INITIAL_IN_STOCK,
                    previous_state=None,
                    current_state=curr_state,
                    should_notify=True,
                    detected_at=now,
                )
                return existing, event
            return existing, None

        if prev_reliable == AvailabilityState.IN_STOCK and curr_state == AvailabilityState.IN_STOCK:
            # Remains in stock - NO repeated alert
            return existing, None

        if prev_reliable != AvailabilityState.IN_STOCK and curr_state == AvailabilityState.IN_STOCK:
            # Restock event! (e.g. OUT_OF_STOCK -> IN_STOCK, COMING_SOON -> IN_STOCK)
            existing.last_transition = now
            event = TransitionEvent(
                product=existing,
                transition_type=TransitionType.RESTOCKED,
                previous_state=prev_reliable,
                current_state=curr_state,
                should_notify=True,
                detected_at=now,
            )
            return existing, event

        if prev_reliable == AvailabilityState.IN_STOCK and curr_state == AvailabilityState.OUT_OF_STOCK:
            existing.last_transition = now
            event = TransitionEvent(
                product=existing,
                transition_type=TransitionType.NOW_OUT_OF_STOCK,
                previous_state=prev_reliable,
                current_state=curr_state,
                should_notify=False,
                detected_at=now,
            )
            return existing, event

        return existing, None

    def mark_missing(self, domain: str, active_ids: set[str]) -> None:
        """Mark products from domain not in active_ids as missing_from_listing."""
        for key, prod in self.products.items():
            if prod.domain == domain:
                if prod.product_id not in active_ids:
                    prod.missing_from_listing = True

