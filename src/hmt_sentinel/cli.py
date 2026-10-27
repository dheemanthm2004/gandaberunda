"""Command-line interface for HMT Gandaberunda Stock Sentinel."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from hmt_sentinel.config import Config, get_config
from hmt_sentinel.discovery import DiscoveryService
from hmt_sentinel.logging_config import setup_logging
from hmt_sentinel.monitoring import MonitoringEngine
from hmt_sentinel.notifications import TelegramNotifier
from hmt_sentinel.state import StateStore

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("hmt_sentinel.cli")


def cmd_monitor(args: argparse.Namespace) -> int:
    """Execute a full monitoring run."""
    config = get_config()
    if args.dry_run:
        config.dry_run = True

    # Validate config (credentials required unless dry_run)
    if not config.dry_run:
        try:
            config.validate_for_monitoring()
        except ValueError as exc:
            logger.error("Configuration error: %s", exc)
            print(f"\n[ERROR] Configuration check failed: {exc}", file=sys.stderr)
            print("Please configure your .env file or environment variables. See .env.example.\n", file=sys.stderr)
            return 1

    engine = MonitoringEngine(config=config)
    summary = engine.run()

    print("\n" + "=" * 50)
    print("           MONITORING RUN SUMMARY")
    print("=" * 50)
    duration = (summary.end_time - summary.start_time).total_seconds() if summary.end_time else 0
    print(f"Duration:                {duration:.2f}s")
    print(f"Store Discovery OK:      {summary.store_discovery_ok}")
    print(f"Store Products Found:    {summary.store_products_found}")
    print(f"Store Products Checked:  {summary.store_checked}")
    print(f".in Discovery OK:        {summary.in_discovery_ok}")
    print(f".in Products Found:      {summary.in_products_found}")
    print(f".in Products Checked:    {summary.in_checked}")
    print("-" * 50)
    print(f"In Stock:                {summary.in_stock}")
    print(f"Out of Stock:            {summary.out_of_stock}")
    print(f"Coming Soon:             {summary.coming_soon}")
    print(f"Unknown / Failed:        {summary.unknown}")
    print(f"Notifications Sent:      {summary.notifications_sent}")
    print(f"Notifications Failed:    {summary.notifications_failed}")
    if summary.errors:
        print("\nErrors encountered:")
        for err in summary.errors:
            print(f"  - {err}")
    print("=" * 50 + "\n")

    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Run dynamic discovery only and display found products without updating state or sending alerts."""
    config = get_config()
    service = DiscoveryService()
    reports = service.discover_all(
        enable_store=config.enable_store,
        enable_in=config.enable_in,
    )

    print("\n" + "=" * 60)
    print("             DYNAMIC DISCOVERY RESULTS")
    print("=" * 60)
    total_found = 0
    for domain, rep in reports.items():
        status_str = "SUCCESS" if rep.success else f"FAILED ({rep.error})"
        print(f"\nWebsite: {domain} [{status_str}]")
        print(f"Matching Gandaberunda Products Found: {len(rep.products)}")
        total_found += len(rep.products)
        for i, p in enumerate(rep.products, 1):
            print(f"  {i}. {p.name}")
            print(f"     URL:   {p.url}")
            print(f"     Price: {p.price or 'N/A'}")
            print(f"     Stock: {p.availability.value} ({p.availability_reason or 'N/A'})")

    print("\n" + "=" * 60)
    print(f"Total Discoverable Gandaberunda Watches: {total_found}")
    print("=" * 60 + "\n")
    return 0


def cmd_telegram_test(args: argparse.Namespace) -> int:
    """Send a test message to Telegram to verify credentials."""
    config = get_config()
    try:
        config.validate()
    except ValueError as exc:
        print(f"\n[ERROR] Telegram credentials incomplete: {exc}", file=sys.stderr)
        return 1

    print("\nSending Telegram test notification...")
    notifier = TelegramNotifier(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        dry_run=False,
    )
    success = notifier.send_test_notification()
    if success:
        print("✅ Telegram test notification sent successfully! Check your Telegram chat.\n")
        return 0
    else:
        print("❌ Failed to deliver test notification. Check bot token, chat ID, and network connection.\n", file=sys.stderr)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Inspect state file and display currently tracked watches."""
    config = get_config()
    store = StateStore(config.state_file)

    print("\n" + "=" * 65)
    print(f"     HMT GANDABERUNDA SENTINEL STATE (file: {config.state_file})")
    print("=" * 65)
    print(f"Schema Version:     {store.version}")
    print(f"Last Run Timestamp: {store.last_run_timestamp or 'Never'}")
    print(f"Tracked Products:   {len(store.products)}")
    print("-" * 65)

    if not store.products:
        print("No products currently tracked. Run 'hmt-sentinel monitor' or 'hmt-sentinel discover'.")
    else:
        for i, (key, p) in enumerate(store.products.items(), 1):
            print(f"{i}. [{p.domain}] {p.name}")
            print(f"   Model:        {p.model_ref or 'N/A'}")
            print(f"   Status:       {p.availability.value} (Last reliable: {p.last_reliable_availability.value if p.last_reliable_availability else 'N/A'})")
            print(f"   Price:        {p.price or 'N/A'}")
            print(f"   URL:          {p.url}")
            print(f"   Last Checked: {p.last_checked.isoformat() if p.last_checked else 'Never'}")
            print(f"   Last Notified:{p.last_notified.isoformat() if p.last_notified else 'Never'}")
            print(f"   Missing:      {p.missing_from_listing}")
            print()

    print("=" * 65 + "\n")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Run automated test suite."""
    import pytest
    pytest_args = ["tests"]
    if args.verbose:
        pytest_args.append("-v")
    print("Running automated test suite with pytest...")
    ret = pytest.main(pytest_args)
    return ret


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hmt-sentinel",
        description="HMT Gandaberunda Stock Sentinel — Autonomous Personal Watch Restock Monitor",
    )
    parser.add_argument("--log-level", default=None, help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # monitor
    p_monitor = subparsers.add_parser("monitor", help="Run a full monitoring cycle")
    p_monitor.add_argument("--dry-run", action="store_true", help="Log notifications without sending to Telegram")

    # discover
    subparsers.add_parser("discover", help="Discover matching Gandaberunda watches without updating state")

    # dry-run
    subparsers.add_parser("dry-run", help="Run full monitoring in dry-run mode (no Telegram alerts)")

    # telegram-test
    subparsers.add_parser("telegram-test", help="Send a test notification to verified Telegram chat")

    # status
    subparsers.add_parser("status", help="Inspect current monitoring state database")

    # test
    p_test = subparsers.add_parser("test", help="Run automated test suite")
    p_test.add_argument("-v", "--verbose", action="store_true", help="Verbose test output")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = get_config()
    log_level = args.log_level or config.log_level
    setup_logging(log_level)

    if args.command == "monitor":
        sys.exit(cmd_monitor(args))
    elif args.command == "discover":
        sys.exit(cmd_discover(args))
    elif args.command == "dry-run":
        args.dry_run = True
        sys.exit(cmd_monitor(args))
    elif args.command == "telegram-test":
        sys.exit(cmd_telegram_test(args))
    elif args.command == "status":
        sys.exit(cmd_status(args))
    elif args.command == "test":
        sys.exit(cmd_test(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
