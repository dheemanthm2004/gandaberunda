"""Tests for monitoring engine orchestration, error isolation, priority, and summaries."""
import argparse
from pathlib import Path
import pytest

from hmt_sentinel.adapters.base import BaseAdapter
from hmt_sentinel.cli import (
    cmd_discover,
    cmd_monitor,
    cmd_status,
    cmd_telegram_test,
)
from hmt_sentinel.config import Config
from hmt_sentinel.models import AvailabilityState, Product
from hmt_sentinel.monitoring import MonitoringEngine
from hmt_sentinel.notifications import TelegramNotifier
from hmt_sentinel.state import StateStore


class MockStoreAdapter(BaseAdapter):
    domain = "hmtwatches.store"

    def __init__(self, products=None, fail_discovery=False):
        self.products = products or []
        self.fail_discovery = fail_discovery
        self.last_error = "Mocked store failure" if fail_discovery else None
        self.checked_products = []

    def discover(self):
        if self.fail_discovery:
            return []
        return [Product.from_dict(p.to_dict()) for p in self.products]

    def check_product(self, product):
        self.checked_products.append(product.product_id)
        return product


class MockInAdapter(BaseAdapter):
    domain = "hmtwatches.in"

    def __init__(self, products=None, fail_discovery=False):
        self.products = products or []
        self.fail_discovery = fail_discovery
        self.last_error = "Mocked .in failure" if fail_discovery else None
        self.checked_products = []

    def discover(self):
        if self.fail_discovery:
            return []
        return [Product.from_dict(p.to_dict()) for p in self.products]

    def check_product(self, product):
        self.checked_products.append(product.product_id)
        return product


def test_store_failure_does_not_prevent_in_checks(tmp_path, mocker):
    state_file = tmp_path / "state.json"
    state_store = StateStore(state_file)

    store_adapter = MockStoreAdapter(fail_discovery=True)
    in_prod = Product(
        domain="hmtwatches.in",
        product_id="in-1216",
        name="HMT Women's Gandaberunda",
        url="https://www.hmtwatches.in/product_overview?id=1216",
        availability=AvailabilityState.IN_STOCK,
    )
    in_adapter = MockInAdapter(products=[in_prod])

    notifier = mocker.MagicMock(spec=TelegramNotifier)
    notifier.notify_restock.return_value = True

    config = Config(
        telegram_bot_token="fake",
        telegram_chat_id="fake",
        state_file=state_file,
        enable_store=True,
        enable_in=True,
    )

    engine = MonitoringEngine(
        config=config,
        state_store=state_store,
        notifier=notifier,
        store_adapter=store_adapter,
        in_adapter=in_adapter,
    )

    summary = engine.run()

    # Store failed, but .in was still discovered and monitored!
    assert summary.store_discovery_ok is False
    assert summary.in_discovery_ok is True
    assert summary.in_products_found == 1
    assert summary.in_checked == 1
    assert summary.in_stock == 1
    assert summary.notifications_sent == 1
    assert len(summary.errors) > 0  # Store failure recorded in errors


def test_in_failure_does_not_invalidate_store_results(tmp_path, mocker):
    state_file = tmp_path / "state.json"
    state_store = StateStore(state_file)

    store_prod = Product(
        domain="hmtwatches.store",
        product_id="store-100",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/store-100",
        availability=AvailabilityState.IN_STOCK,
    )
    store_adapter = MockStoreAdapter(products=[store_prod])
    in_adapter = MockInAdapter(fail_discovery=True)

    notifier = mocker.MagicMock(spec=TelegramNotifier)
    notifier.notify_restock.return_value = True

    config = Config(
        telegram_bot_token="fake",
        telegram_chat_id="fake",
        state_file=state_file,
        enable_store=True,
        enable_in=True,
    )

    engine = MonitoringEngine(
        config=config,
        state_store=state_store,
        notifier=notifier,
        store_adapter=store_adapter,
        in_adapter=in_adapter,
    )

    summary = engine.run()

    assert summary.store_discovery_ok is True
    assert summary.store_products_found == 1
    assert summary.in_discovery_ok is False
    assert summary.in_stock == 1
    assert summary.notifications_sent == 1

    # Verify store product was saved to state disk file
    reloaded_store = StateStore(state_file)
    assert reloaded_store.get_product("hmtwatches.store", "store-100") is not None


def test_dry_run_mode(tmp_path, mocker):
    state_file = tmp_path / "state.json"
    state_store = StateStore(state_file)

    store_prod = Product(
        domain="hmtwatches.store",
        product_id="store-100",
        name="HMT Gandaberunda JLGG 01",
        url="https://www.hmtwatches.store/product/store-100",
        availability=AvailabilityState.IN_STOCK,
    )
    store_adapter = MockStoreAdapter(products=[store_prod])
    in_adapter = MockInAdapter(products=[])

    notifier = TelegramNotifier(
        bot_token="fake",
        chat_id="fake",
        dry_run=True,
    )

    config = Config(
        telegram_bot_token="fake",
        telegram_chat_id="fake",
        state_file=state_file,
        dry_run=True,
    )

    engine = MonitoringEngine(
        config=config,
        state_store=state_store,
        notifier=notifier,
        store_adapter=store_adapter,
        in_adapter=in_adapter,
    )

    summary = engine.run()
    # In dry run, notification is simulated and marked sent
    assert summary.notifications_sent == 1
    assert summary.in_stock == 1


def test_config_validation():
    # Missing token
    c1 = Config(telegram_bot_token="", telegram_chat_id="123")
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        c1.validate()

    # Missing chat ID
    c2 = Config(telegram_bot_token="token", telegram_chat_id="")
    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        c2.validate()

    # Both disabled
    c3 = Config(telegram_bot_token="token", telegram_chat_id="123", enable_store=False, enable_in=False)
    with pytest.raises(ValueError, match="Both ENABLE_STORE and ENABLE_IN are disabled"):
        c3.validate()


def test_cli_discover_command(mocker):
    mocker.patch("hmt_sentinel.cli.DiscoveryService.discover_all", return_value={})
    args = argparse.Namespace(dry_run=False, log_level=None)
    ret = cmd_discover(args)
    assert ret == 0


def test_cli_status_command(tmp_path, mocker):
    state_file = tmp_path / "state.json"
    mocker.patch("hmt_sentinel.cli.get_config", return_value=Config(state_file=state_file))
    args = argparse.Namespace(log_level=None)
    ret = cmd_status(args)
    assert ret == 0


def test_cli_telegram_test_command(mocker):
    mocker.patch("hmt_sentinel.cli.get_config", return_value=Config(telegram_bot_token="token", telegram_chat_id="chat"))
    mocker.patch("hmt_sentinel.notifications.TelegramNotifier.send_test_notification", return_value=True)
    args = argparse.Namespace(log_level=None)
    ret = cmd_telegram_test(args)
    assert ret == 0
