"""Pure calculation functions for fees, funding, volume."""

from typing import Dict, Tuple

from ..models.domain import FundingKind


def hourly_boundaries_crossed(hold_minutes: float) -> int:
    """Calculate number of hourly funding boundaries crossed.
    
    Args:
        hold_minutes: Planned hold time in minutes
    
    Returns:
        Number of full hourly payments
    """
    hours = hold_minutes / 60.0
    return int(hours)


def funding_hourly_rate(funding_rate: float, funding_kind: FundingKind) -> float:
    """Convert funding rate to hourly rate.
    
    Args:
        funding_rate: Funding rate from API
        funding_kind: "hourly" or "8h"
    
    Returns:
        Hourly funding rate
    """
    if funding_kind == FundingKind.EIGHT_HOUR:
        return funding_rate / 8.0
    return funding_rate


def funding_pnl_usd(
    side: str,
    notional: float,
    hourly_funding_rate: float,
    payments: int,
) -> float:
    """Calculate funding PnL in USD.
    
    Args:
        side: "LONG" (side=+1) or "SHORT" (side=-1)
        notional: Position notional value
        hourly_funding_rate: Hourly funding rate
        payments: Number of hourly payments
    
    Returns:
        Funding PnL (negative means you pay, positive means you receive)
    """
    side_multiplier = 1.0 if side.upper() == "LONG" else -1.0
    return -side_multiplier * notional * hourly_funding_rate * payments


def calculate_funding_pnl(
    side: str,
    notional: float,
    hourly_funding_rate: float,
    hold_minutes: int,
    funding_kind: FundingKind = FundingKind.HOURLY,
) -> float:
    """Calculate funding PnL for a position.
    
    Args:
        side: "LONG" (side=+1) or "SHORT" (side=-1)
        notional: Position notional value
        hourly_funding_rate: Funding rate from API (assumed hourly)
        hold_minutes: Planned hold time in minutes
        funding_kind: "hourly" or "8h" (divides rate by 8)
    
    Returns:
        Funding PnL (negative means you pay, positive means you receive)
    """
    hourly_rate = funding_hourly_rate(hourly_funding_rate, funding_kind)
    payments = hourly_boundaries_crossed(hold_minutes)
    return funding_pnl_usd(side, notional, hourly_rate, payments)


def fee_rate(
    fee_mode: str,
    taker_fee: float,
    maker_fee: float,
    fill_prob: float = 1.0,
) -> Tuple[float, float]:
    """Calculate open and close fee rates.
    
    Args:
        fee_mode: "taker", "maker", or "both" (taker open, maker close)
        taker_fee: Taker fee rate
        maker_fee: Maker fee rate
        fill_prob: Probability of maker fill (0..1)
    
    Returns:
        Tuple of (open_fee_rate, close_fee_rate)
    """
    if fee_mode.lower() == "maker":
        open_rate = maker_fee
        close_rate = maker_fee
    elif fee_mode.lower() == "both":
        open_rate = taker_fee
        close_rate = maker_fee
    else:  # default taker
        open_rate = taker_fee
        close_rate = taker_fee
    
    # Apply fill probability for maker fees
    if open_rate == maker_fee:
        open_rate = fill_prob * maker_fee + (1 - fill_prob) * taker_fee
    if close_rate == maker_fee:
        close_rate = fill_prob * maker_fee + (1 - fill_prob) * taker_fee
    
    return open_rate, close_rate


def calculate_fees(
    notional: float,
    taker_fee: float = 0.00045,
    maker_fee: float = 0.00015,
    fee_mode: str = "taker",
    fill_prob: float = 1.0,
    fallback_taker_after_sec: int | None = None,
    open_fee_mode: str | None = None,
    close_fee_mode: str | None = None,
) -> Tuple[float, Dict]:
    """Calculate round-trip fees with fill probability modeling.
    
    Args:
        notional: Position notional value
        taker_fee: Taker fee rate
        maker_fee: Maker fee rate
        fee_mode: "taker", "maker", or "both" (taker open, maker close) - used as fallback
        fill_prob: Probability of maker fill (0..1)
        fallback_taker_after_sec: If not None, probability of fallback to taker after this time
        open_fee_mode: Override for open fee mode ("maker" or "taker")
        close_fee_mode: Override for close fee mode ("maker" or "taker")
    
    Returns:
        Tuple of (total_fees, details_dict)
    """
    # Determine fee modes
    if open_fee_mode:
        open_mode = open_fee_mode.lower()
    elif fee_mode.lower() == "both":
        open_mode = "taker"
    elif fee_mode.lower() == "maker":
        open_mode = "maker"
    else:
        open_mode = "taker"
    
    if close_fee_mode:
        close_mode = close_fee_mode.lower()
    elif fee_mode.lower() == "both":
        close_mode = "maker"
    elif fee_mode.lower() == "maker":
        close_mode = "maker"
    else:
        close_mode = "taker"
    
    # Calculate fee rates
    open_fee_rate, _ = fee_rate(open_mode, taker_fee, maker_fee, fill_prob)
    _, close_fee_rate = fee_rate(close_mode, taker_fee, maker_fee, fill_prob)
    
    total_fees = notional * (open_fee_rate + close_fee_rate)
    
    return total_fees, {
        "open_fee_mode": open_mode,
        "close_fee_mode": close_mode,
        "open_fee_rate": open_fee_rate,
        "close_fee_rate": close_fee_rate,
        "open_fee": notional * open_fee_rate,
        "close_fee": notional * close_fee_rate,
        "fill_prob": fill_prob,
    }


def calculate_volume(notional: float, fill_prob: float = 1.0) -> float:
    """Calculate round-trip volume (open + close) with fill probability.
    
    Args:
        notional: Position notional value
        fill_prob: Probability of fill (0..1)
    
    Returns:
        Expected volume (symmetric: 2 * notional * fill_prob)
    """
    return notional * 2.0 * fill_prob


def roundtrips_needed(
    remaining_volume: float,
    notional_per_trade: float,
    fill_prob: float = 1.0,
) -> int:
    """Calculate number of round-trips needed to reach target volume.
    
    Args:
        remaining_volume: Remaining volume to achieve
        notional_per_trade: Notional per trade
        fill_prob: Probability of fill (0..1)
    
    Returns:
        Number of round-trips needed
    """
    volume_per_trade = calculate_volume(notional_per_trade, fill_prob)
    if volume_per_trade <= 0:
        return 0
    return int(remaining_volume / volume_per_trade)


def estimate_liquidation_move(leverage: float, margin_mode: str | None = None) -> float:
    """Estimate liquidation move as percentage.
    
    For isolated margin, liquidation happens at ~100% loss of margin.
    For cross margin, it's more complex but roughly similar.
    
    Args:
        leverage: Leverage multiplier
        margin_mode: "isolated" or None (cross)
    
    Returns:
        Percentage move to liquidation
    """
    if margin_mode == "isolated":
        return 100.0 / leverage
    return 90.0 / leverage  # Slightly more conservative for cross

