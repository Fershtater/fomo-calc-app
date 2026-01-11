"""Domain models (dataclasses) for farmcalc."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class FundingKind(str, Enum):
    """Funding rate kind."""
    HOURLY = "hourly"
    EIGHT_HOUR = "8h"


@dataclass
class Plan:
    """Farming plan configuration."""
    deposit: float = 1000.0
    default_margin: float = 100.0
    default_leverage: float = 10.0
    target_volume: float = 10000.0
    target_frozen: float = 0.0
    unfreeze_factor: float = 1.75
    level_factor: float = 0.25


@dataclass
class Stats:
    """Farming statistics."""
    total_volume_done: float = 0.0
    total_fees: float = 0.0
    total_funding_pnl: float = 0.0
    frozen_remaining: float = 0.0
    estimated_fomo_minted: float = 0.0


@dataclass
class Trade:
    """A trade record."""
    id: str
    coin: str
    side: str  # "LONG" or "SHORT"
    leverage: float
    margin: float
    notional: float
    open_timestamp: str
    planned_hold_min: int
    expected_fees: float
    expected_funding_pnl: float
    open_price: Optional[float] = None
    close_price: Optional[float] = None
    close_timestamp: Optional[str] = None
    realized_pnl: Optional[float] = None
    # Limit order fields
    open_limit_px: Optional[float] = None
    close_limit_px: Optional[float] = None
    fill_prob: float = 1.0
    fallback_taker_after_sec: Optional[int] = None
    open_fee_mode: str = "maker"
    close_fee_mode: str = "maker"
    actual_close_fee_mode: Optional[str] = None


class ProposalStatus(str, Enum):
    """Proposal status."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class Proposal:
    """A trade proposal that can be accepted/rejected via Telegram."""
    id: str
    coin: str
    side: str  # "LONG" or "SHORT"
    score: float
    reasons: List[str]
    metrics: Dict
    suggested_prices: Dict  # open_limit_px, close_limit_px, best_bid, best_ask
    offsets: Dict  # open_offset_bps, close_offset_bps
    fill_probs: Dict  # open_fill_prob, close_fill_prob
    margin: float
    leverage: float
    hold_min: int
    fee_mode: str
    funding_kind: str
    funding_raw: float
    funding_hourly: float
    created_at: str
    expires_at: str
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    status: str = ProposalStatus.PENDING.value
    decided_at_utc: Optional[str] = None  # When decision was made
    decided_by_user_id: Optional[int] = None  # Telegram user ID who decided
    decision: Optional[str] = None  # "ACCEPT" or "REJECT"


@dataclass
class State:
    """Application state."""
    plan: Plan
    stats: Stats
    trades: List[Trade]
    proposals: Dict[str, Proposal] = field(default_factory=dict)  # proposal_id -> Proposal
    watcher_enabled: bool = True
    schema_version: int = 2  # Bumped for proposals support


@dataclass
class WatchThresholds:
    """Thresholds for safe entry evaluation."""
    spread_max_bps: float = 3.0
    mark_dev_max_bps: float = 5.0
    oracle_dev_max_bps: float = 10.0
    funding_max: float = 0.00002  # For hourly, adjust for 8h
    min_day_ntl_vlm: float = 0.0


@dataclass
class WatchConfig:
    """Watch mode configuration."""
    enabled: bool = False
    poll_interval_sec: float = 5.0
    top_n: int = 25
    side: str = "either"  # "long", "short", "either"
    open_offset_bps: float = 0.0
    close_offset_bps: float = 0.0
    funding_kind: str = "hourly"  # "hourly" or "8h"
    thresholds: WatchThresholds = field(default_factory=WatchThresholds)
    cooldown_sec: float = 300.0  # 5 minutes default
    sentiment_enabled: bool = False
    telegram_enabled: bool = True


@dataclass
class WatchState:
    """Watch mode state."""
    config: WatchConfig
    last_poll_time: Optional[str] = None
    last_alerts: List[Dict] = field(default_factory=list)
    last_alert_ts: Dict[str, float] = field(default_factory=dict)  # key: "coin_side", value: timestamp
    last_safe_snapshot: Dict[str, Dict] = field(default_factory=dict)  # key: coin, value: snapshot
    is_running: bool = False
    enabled: bool = True  # Controls whether watcher should poll/alert
    muted_coins: Dict[str, float] = field(default_factory=dict)  # key: coin, value: unmute timestamp
    last_proposal_time: float = 0.0  # For spam guard


@dataclass
class Asset:
    """Market asset data."""
    coin: str
    max_leverage: float
    only_isolated: bool
    margin_mode: Optional[str]
    funding: float
    mark_px: float
    mid_px: float
    oracle_px: float
    open_interest: float
    day_ntl_vlm: float

