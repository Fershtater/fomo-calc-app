"""Adaptive fill probability estimation for maker limit orders."""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FillHistory:
    """Per-coin fill history for calibration."""
    coin: str
    snapshots: List[Dict] = field(default_factory=list)  # Last M snapshots
    feedback_count: int = 0
    filled_count: int = 0
    missed_count: int = 0
    max_snapshots: int = 20


@dataclass
class FillCalibration:
    """Calibration parameters for fill probability."""
    base_prob: float = 0.8  # Base fill probability
    spread_factor: float = -0.5  # How spread affects probability
    depth_factor: float = 0.3  # How depth affects probability
    volatility_factor: float = -0.2  # How volatility affects probability
    offset_factor: float = 0.4  # How aggressive offset affects probability


def calculate_micro_volatility(snapshots: List[Dict], window: int = 5) -> float:
    """Calculate short-term micro-volatility from price changes.
    
    Args:
        snapshots: List of historical snapshots with mid prices
        window: Number of recent snapshots to use
    
    Returns:
        Volatility proxy (0-1 scale)
    """
    if len(snapshots) < 2:
        return 0.0
    
    recent = snapshots[-window:] if len(snapshots) > window else snapshots
    if len(recent) < 2:
        return 0.0
    
    mid_prices = [s.get("mid", 0) for s in recent if s.get("mid", 0) > 0]
    if len(mid_prices) < 2:
        return 0.0
    
    # Calculate coefficient of variation
    changes = []
    for i in range(1, len(mid_prices)):
        if mid_prices[i-1] > 0:
            change = abs(mid_prices[i] - mid_prices[i-1]) / mid_prices[i-1]
            changes.append(change)
    
    if not changes:
        return 0.0
    
    # Average relative change as volatility proxy
    avg_change = sum(changes) / len(changes)
    # Normalize to 0-1 scale (cap at 0.01 = 1% average change)
    return min(avg_change / 0.01, 1.0)


def estimate_fill_probability(
    spread_bps: float,
    depth_top: float,
    notional_size: float,
    offset_bps: float,
    snapshots: Optional[List[Dict]] = None,
    calibration: Optional[FillCalibration] = None,
    sentiment_bias: Optional[str] = None,
) -> float:
    """Estimate fill probability for a maker limit order.
    
    Args:
        spread_bps: Current spread in basis points
        depth_top: Top-of-book depth
        notional_size: Order notional size
        offset_bps: Price offset in basis points (more aggressive = higher)
        snapshots: Historical snapshots for volatility calculation
        calibration: Calibration parameters (uses defaults if None)
        sentiment_bias: Optional sentiment bias ("LONG", "SHORT", "NEUTRAL")
    
    Returns:
        Fill probability between 0 and 1
    """
    if calibration is None:
        calibration = FillCalibration()
    
    # Base probability
    prob = calibration.base_prob
    
    # Spread effect: tighter spread = higher probability
    # Normalize spread: 0 bps = 1.0, 10 bps = 0.0
    spread_norm = max(0, 1.0 - (spread_bps / 10.0))
    prob += calibration.spread_factor * (1.0 - spread_norm)
    
    # Depth effect: deeper book = higher probability
    # Normalize depth: 10k = 1.0, 1k = 0.0
    depth_norm = min(1.0, max(0.0, (depth_top - 1000.0) / 9000.0))
    prob += calibration.depth_factor * depth_norm
    
    # Size vs depth: if order is large relative to depth, lower probability
    if depth_top > 0:
        size_ratio = min(1.0, notional_size / depth_top)
        prob -= 0.2 * size_ratio  # Penalize large orders
    
    # Volatility effect: higher volatility = lower probability (for strict post-only)
    if snapshots:
        volatility = calculate_micro_volatility(snapshots)
        prob += calibration.volatility_factor * volatility
    
    # Offset effect: more aggressive (higher offset) = higher probability
    # Normalize offset: 0 bps = 0.0, 50 bps = 1.0
    offset_norm = min(1.0, offset_bps / 50.0)
    prob += calibration.offset_factor * offset_norm
    
    # Sentiment bias (weak modifier, document clearly)
    if sentiment_bias:
        # Very weak effect: ±5% max
        if sentiment_bias == "LONG":
            prob += 0.02  # Slightly higher for longs
        elif sentiment_bias == "SHORT":
            prob -= 0.02  # Slightly lower for shorts
    
    # Clamp to [0, 1]
    return max(0.0, min(1.0, prob))


def update_calibration_from_feedback(
    history: FillHistory,
    action: str,  # "open" or "close"
    filled: bool,
) -> FillCalibration:
    """Update calibration based on user feedback.
    
    Args:
        history: Fill history for the coin
        action: "open" or "close"
        filled: Whether the order was filled
    
    Returns:
        Updated calibration
    """
    history.feedback_count += 1
    if filled:
        history.filled_count += 1
    else:
        history.missed_count += 1
    
    # Simple calibration: adjust base probability based on observed fill rate
    total = history.filled_count + history.missed_count
    if total > 0:
        observed_rate = history.filled_count / total
        # Adjust base_prob towards observed rate (with some smoothing)
        calibration = FillCalibration()
        calibration.base_prob = 0.7 * calibration.base_prob + 0.3 * observed_rate
        return calibration
    
    return FillCalibration()


class FillModelService:
    """Service for managing fill probability estimation."""
    
    def __init__(self):
        """Initialize fill model service."""
        self._histories: Dict[str, FillHistory] = {}
        self._calibrations: Dict[str, FillCalibration] = {}
    
    def get_history(self, coin: str) -> FillHistory:
        """Get or create fill history for a coin."""
        if coin not in self._histories:
            self._histories[coin] = FillHistory(coin=coin)
        return self._histories[coin]
    
    def add_snapshot(self, coin: str, snapshot: Dict):
        """Add a market snapshot for volatility calculation.
        
        Args:
            coin: Coin symbol
            snapshot: Snapshot dict with mid, bid, ask, spread, depth_top
        """
        history = self.get_history(coin)
        history.snapshots.append(snapshot)
        
        # Keep only last M snapshots
        if len(history.snapshots) > history.max_snapshots:
            history.snapshots = history.snapshots[-history.max_snapshots:]
    
    def estimate_fill_prob(
        self,
        coin: str,
        spread_bps: float,
        depth_top: float,
        notional_size: float,
        offset_bps: float,
        sentiment_bias: Optional[str] = None,
    ) -> float:
        """Estimate fill probability for a coin.
        
        Args:
            coin: Coin symbol
            spread_bps: Current spread
            depth_top: Top-of-book depth
            notional_size: Order size
            offset_bps: Price offset
            sentiment_bias: Optional sentiment
        
        Returns:
            Fill probability (0-1)
        """
        history = self.get_history(coin)
        calibration = self._calibrations.get(coin, FillCalibration())
        
        return estimate_fill_probability(
            spread_bps=spread_bps,
            depth_top=depth_top,
            notional_size=notional_size,
            offset_bps=offset_bps,
            snapshots=history.snapshots,
            calibration=calibration,
            sentiment_bias=sentiment_bias,
        )
    
    def record_feedback(
        self,
        coin: str,
        action: str,
        filled: bool,
    ):
        """Record user feedback on fill outcome.
        
        Args:
            coin: Coin symbol
            action: "open" or "close"
            filled: Whether order was filled
        """
        history = self.get_history(coin)
        calibration = update_calibration_from_feedback(history, action, filled)
        self._calibrations[coin] = calibration
        
        logger.info(
            f"Fill feedback recorded for {coin} {action}: "
            f"filled={filled}, new base_prob={calibration.base_prob:.2f}"
        )

