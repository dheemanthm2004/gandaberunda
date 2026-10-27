"""Tests for state management, transitions, and persistence."""
import json
from pathlib import Path
import pytest

from hmt_sentinel.models import AvailabilityState, Product, utcnow
from hmt_sentinel.state import StateStore, TransitionType


def test_initial_out_of_stock_no_notification(tmp_path):
    store = StateStore(tmp_path / "state.json")
    prod = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.OUT_OF_STOCK,
    )
    saved_prod, event = store.register_or_update(prod)
    assert event is None
    assert saved_prod.availability == AvailabilityState.OUT_OF_STOCK
    assert saved_prod.last_reliable_availability == AvailabilityState.OUT_OF_STOCK


def test_repeated_out_of_stock_no_notification(tmp_path):
    store = StateStore(tmp_path / "state.json")
    prod1 = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.OUT_OF_STOCK,
    )
    store.register_or_update(prod1)

    prod2 = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.OUT_OF_STOCK,
    )
    _, event = store.register_or_update(prod2)
    assert event is None


def test_out_of_stock_to_in_stock_transition(tmp_path):
    store = StateStore(tmp_path / "state.json")
    prod_oos = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.OUT_OF_STOCK,
    )
    store.register_or_update(prod_oos)

    prod_in = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.IN_STOCK,
    )
    saved_prod, event = store.register_or_update(prod_in)
    assert event is not None
    assert event.should_notify is True
    assert event.transition_type == TransitionType.RESTOCKED
    assert event.previous_state == AvailabilityState.OUT_OF_STOCK
    assert event.current_state == AvailabilityState.IN_STOCK


def test_repeated_in_stock_no_duplicate_alert(tmp_path):
    store = StateStore(tmp_path / "state.json")
    prod_in1 = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.IN_STOCK,
    )
    store.register_or_update(prod_in1)

    prod_in2 = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.IN_STOCK,
    )
    _, event = store.register_or_update(prod_in2)
    assert event is None


def test_in_stock_to_out_of_stock_no_alert(tmp_path):
    store = StateStore(tmp_path / "state.json")
    prod_in = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.IN_STOCK,
    )
    store.register_or_update(prod_in)

    prod_oos = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.OUT_OF_STOCK,
    )
    _, event = store.register_or_update(prod_oos)
    assert event is not None
    assert event.should_notify is False
    assert event.transition_type == TransitionType.NOW_OUT_OF_STOCK


def test_subsequent_restock_triggers_new_alert(tmp_path):
    store = StateStore(tmp_path / "state.json")
    prod = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.IN_STOCK,
    )
    store.register_or_update(prod)

    # Becomes OOS
    prod.availability = AvailabilityState.OUT_OF_STOCK
    store.register_or_update(prod)

    # Later becomes IN_STOCK again
    prod.availability = AvailabilityState.IN_STOCK
    _, event = store.register_or_update(prod)
    assert event is not None
    assert event.should_notify is True
    assert event.transition_type == TransitionType.RESTOCKED


def test_newly_discovered_in_stock_triggers_initial_alert(tmp_path):
    store = StateStore(tmp_path / "state.json")
    prod = Product(
        domain="hmtwatches.store",
        product_id="brand-new-1",
        name="HMT Gandaberunda New Edition",
        url="https://www.hmtwatches.store/product/brand-new-1",
        availability=AvailabilityState.IN_STOCK,
    )
    _, event = store.register_or_update(prod)
    assert event is not None
    assert event.should_notify is True
    assert event.transition_type == TransitionType.INITIAL_IN_STOCK


def test_unknown_state_preserves_last_reliable_state(tmp_path):
    store = StateStore(tmp_path / "state.json")
    prod = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.OUT_OF_STOCK,
    )
    store.register_or_update(prod)

    # Subsequent check failed / returned UNKNOWN
    prod_unknown = Product(
        domain="hmtwatches.store",
        product_id="prod-1",
        name="HMT Gandaberunda",
        url="https://www.hmtwatches.store/product/prod-1",
        availability=AvailabilityState.UNKNOWN,
        availability_reason="fetch_timeout",
    )
    saved_prod, event = store.register_or_update(prod_unknown)
    assert event is None
    assert saved_prod.availability == AvailabilityState.UNKNOWN
    # Critical requirement: last_reliable_availability is preserved as OUT_OF_STOCK
    assert saved_prod.last_reliable_availability == AvailabilityState.OUT_OF_STOCK


def test_coming_soon_to_in_stock_transition(tmp_path):
    store = StateStore(tmp_path / "state.json")
    prod = Product(
        domain="hmtwatches.in",
        product_id="1216",
        name="HMT Women's Gandaberunda JLGL 01",
        url="https://www.hmtwatches.in/product_overview?id=1216",
        availability=AvailabilityState.COMING_SOON,
    )
    store.register_or_update(prod)

    # Subsequently confirmed in stock
    prod_in = Product(
        domain="hmtwatches.in",
        product_id="1216",
        name="HMT Women's Gandaberunda JLGL 01",
        url="https://www.hmtwatches.in/product_overview?id=1216",
        availability=AvailabilityState.IN_STOCK,
    )
    _, event = store.register_or_update(prod_in)
    assert event is not None
    assert event.should_notify is True
    assert event.transition_type == TransitionType.RESTOCKED
    assert event.previous_state == AvailabilityState.COMING_SOON


def test_independent_domain_availability(tmp_path):
    store = StateStore(tmp_path / "state.json")

    # Store product is in stock
    prod_store = Product(
        domain="hmtwatches.store",
        product_id="ganda-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/ganda-1",
        availability=AvailabilityState.IN_STOCK,
    )
    store.register_or_update(prod_store)

    # .in product is out of stock
    prod_in = Product(
        domain="hmtwatches.in",
        product_id="ganda-1",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.in/product_overview?id=ganda-1",
        availability=AvailabilityState.OUT_OF_STOCK,
    )
    store.register_or_update(prod_in)

    p_store = store.get_product("hmtwatches.store", "ganda-1")
    p_in = store.get_product("hmtwatches.in", "ganda-1")

    assert p_store.availability == AvailabilityState.IN_STOCK
    assert p_in.availability == AvailabilityState.OUT_OF_STOCK
    assert p_store.key != p_in.key


def test_atomic_persistence_and_reload(tmp_path):
    state_file = tmp_path / "state.json"
    store = StateStore(state_file)
    prod = Product(
        domain="hmtwatches.store",
        product_id="p-100",
        name="HMT Gandaberunda",
        url="https://www.hmtwatches.store/product/p-100",
        price="₹2599",
        model_ref="JLGG 01",
        availability=AvailabilityState.IN_STOCK,
    )
    store.register_or_update(prod)
    store.save()

    # Re-load in fresh store instance
    new_store = StateStore(state_file)
    loaded_p = new_store.get_product("hmtwatches.store", "p-100")
    assert loaded_p is not None
    assert loaded_p.name == "HMT Gandaberunda"
    assert loaded_p.price == "₹2599"
    assert loaded_p.model_ref == "JLGG 01"
    assert loaded_p.availability == AvailabilityState.IN_STOCK


def test_corrupted_state_recovery_from_backup(tmp_path):
    state_file = tmp_path / "state.json"
    backup_file = tmp_path / "state.json.bak"

    # Write valid state to backup
    valid_data = {
        "version": 1,
        "products": {
            "hmtwatches.store::p-valid": {
                "domain": "hmtwatches.store",
                "product_id": "p-valid",
                "name": "HMT Gandaberunda Backup",
                "url": "https://www.hmtwatches.store/product/p-valid",
                "availability": "OUT_OF_STOCK",
            }
        },
    }
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(valid_data, f)

    # Write corrupt data to primary file
    with open(state_file, "w", encoding="utf-8") as f:
        f.write("{ corrupt json truncated...")

    # Load should recover from backup
    store = StateStore(state_file)
    prod = store.get_product("hmtwatches.store", "p-valid")
    assert prod is not None
    assert prod.name == "HMT Gandaberunda Backup"


def test_mark_missing_from_listing(tmp_path):
    store = StateStore(tmp_path / "state.json")
    prod1 = Product(
        domain="hmtwatches.store",
        product_id="p-1",
        name="Watch 1",
        url="https://www.hmtwatches.store/product/p-1",
    )
    prod2 = Product(
        domain="hmtwatches.store",
        product_id="p-2",
        name="Watch 2",
        url="https://www.hmtwatches.store/product/p-2",
    )
    store.register_or_update(prod1)
    store.register_or_update(prod2)

    # Run discovery where only p-1 is active
    store.mark_missing("hmtwatches.store", {"p-1"})
    assert store.get_product("hmtwatches.store", "p-1").missing_from_listing is False
    assert store.get_product("hmtwatches.store", "p-2").missing_from_listing is True

