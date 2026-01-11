"""Configuration management from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Settings:
    """Application settings loaded from environment variables."""
    
    # Hyperliquid API
    hyperliquid_api_url: str = "https://api.hyperliquid.xyz/info"
    
    # File paths
    farm_state_path: Path = Path.home() / ".farmcalc_state.json"
    watch_state_path: Path = Path.home() / ".farmcalc_watch_state.json"
    coingecko_cache_path: Path = Path.home() / ".farmcalc_coingecko_cache.json"
    coingecko_cache_ttl_sec: float = 3600.0  # 1 hour
    
    # Default fees
    default_taker_fee: float = 0.00045
    default_maker_fee: float = 0.00015
    
    # Telegram
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_parse_mode: str = "HTML"
    telegram_owner_id: Optional[int] = None
    telegram_allowed_chat_id: Optional[str] = None  # Optional chat ID restriction
    telegram_webhook_url: Optional[str] = None
    telegram_secret_token: Optional[str] = None
    telegram_control_plane: bool = True  # Enable Telegram control features
    proposal_expiry_minutes: int = 15
    telegram_spam_guard_sec: float = 15.0  # Min seconds between proposal messages
    
    # Watcher defaults
    poll_interval_floor_sec: float = 2.0
    meta_cache_ttl_sec: float = 2.0
    
    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        owner_id_str = os.getenv("TELEGRAM_OWNER_ID", "")
        owner_id = int(owner_id_str.strip()) if owner_id_str.strip().isdigit() else None
        
        return cls(
            hyperliquid_api_url=os.getenv("HL_INFO_URL", "https://api.hyperliquid.xyz/info"),
            farm_state_path=Path(os.getenv("FARM_STATE_PATH", str(Path.home() / ".farmcalc_state.json"))),
            watch_state_path=Path(os.getenv("WATCH_STATE_PATH", str(Path.home() / ".farmcalc_watch_state.json"))),
            coingecko_cache_path=Path(os.getenv("COINGECKO_CACHE_PATH", str(Path.home() / ".farmcalc_coingecko_cache.json"))),
            coingecko_cache_ttl_sec=float(os.getenv("COINGECKO_CACHE_TTL_SEC", "3600.0")),
            default_taker_fee=float(os.getenv("DEFAULT_TAKER_FEE", "0.00045")),
            default_maker_fee=float(os.getenv("DEFAULT_MAKER_FEE", "0.00015")),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            telegram_parse_mode=os.getenv("TELEGRAM_PARSE_MODE", "HTML"),
            telegram_owner_id=owner_id,
            telegram_allowed_chat_id=os.getenv("TELEGRAM_ALLOWED_CHAT_ID"),
            telegram_webhook_url=os.getenv("TELEGRAM_WEBHOOK_URL"),
            telegram_secret_token=os.getenv("TELEGRAM_SECRET_TOKEN"),
            telegram_control_plane=os.getenv("TELEGRAM_CONTROL_PLANE", "true").lower() == "true",
            proposal_expiry_minutes=int(os.getenv("PROPOSAL_EXPIRY_MINUTES", "15")),
            telegram_spam_guard_sec=float(os.getenv("TELEGRAM_SPAM_GUARD_SEC", "15.0")),
            poll_interval_floor_sec=float(os.getenv("POLL_INTERVAL_FLOOR_SEC", "2.0")),
            meta_cache_ttl_sec=float(os.getenv("META_CACHE_TTL_SEC", "2.0")),
        )
    
    @property
    def telegram_enabled(self) -> bool:
        """Check if Telegram is configured."""
        return bool(self.telegram_bot_token and self.telegram_chat_id)

