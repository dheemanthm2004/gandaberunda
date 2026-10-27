"""Configuration loaded from environment variables / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    notify_on_failure: bool = field(default_factory=lambda: os.getenv("NOTIFY_ON_FAILURE", "0") == "1")
    request_timeout: int = field(default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT", "20")))
    max_retries: int = field(default_factory=lambda: int(os.getenv("MAX_RETRIES", "3")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    dry_run: bool = field(default_factory=lambda: os.getenv("DRY_RUN", "0") == "1")
    enable_store: bool = field(default_factory=lambda: os.getenv("ENABLE_STORE", "1") == "1")
    enable_in: bool = field(default_factory=lambda: os.getenv("ENABLE_IN", "1") == "1")
    state_file: Path = field(default_factory=lambda: Path(os.getenv("STATE_FILE", "state.json")))

    def validate(self) -> None:
        """Raise ValueError if required fields are missing."""
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set. See .env.example.")
        if not self.telegram_chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is not set. See .env.example.")
        if not self.enable_store and not self.enable_in:
            raise ValueError("Both ENABLE_STORE and ENABLE_IN are disabled. Nothing to monitor.")

    def validate_for_monitoring(self) -> None:
        """Full validation required before a real monitoring run."""
        self.validate()


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
