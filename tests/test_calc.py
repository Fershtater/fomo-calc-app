"""Tests for calculation functions."""

import pytest

from farmcalc.models.domain import FundingKind
from farmcalc.services.calc import (
    calculate_fees,
    calculate_funding_pnl,
    calculate_volume,
    funding_hourly_rate,
    hourly_boundaries_crossed,
    roundtrips_needed,
)


def test_hourly_boundaries_crossed():
    """Test hourly boundary calculation."""
    assert hourly_boundaries_crossed(30) == 0
    assert hourly_boundaries_crossed(60) == 1
    assert hourly_boundaries_crossed(90) == 1
    assert hourly_boundaries_crossed(120) == 2


def test_funding_hourly_rate():
    """Test funding rate conversion."""
    assert funding_hourly_rate(0.0001, FundingKind.HOURLY) == 0.0001
    assert funding_hourly_rate(0.0008, FundingKind.EIGHT_HOUR) == 0.0001


def test_calculate_funding_pnl():
    """Test funding PnL calculation."""
    # LONG position, positive funding (pays)
    pnl = calculate_funding_pnl("LONG", 1000.0, 0.0001, 60, FundingKind.HOURLY)
    assert pnl < 0  # Long pays when funding is positive
    
    # SHORT position, positive funding (receives)
    pnl = calculate_funding_pnl("SHORT", 1000.0, 0.0001, 60, FundingKind.HOURLY)
    assert pnl > 0  # Short receives when funding is positive


def test_calculate_volume():
    """Test volume calculation."""
    assert calculate_volume(1000.0, 1.0) == 2000.0
    assert calculate_volume(1000.0, 0.5) == 1000.0


def test_calculate_fees():
    """Test fee calculation."""
    fees, details = calculate_fees(1000.0, 0.00045, 0.00015, "taker")
    assert fees > 0
    assert details["open_fee_mode"] == "taker"
    assert details["close_fee_mode"] == "taker"
    
    fees, details = calculate_fees(1000.0, 0.00045, 0.00015, "maker")
    assert details["open_fee_mode"] == "maker"
    assert details["close_fee_mode"] == "maker"


def test_roundtrips_needed():
    """Test roundtrips calculation."""
    assert roundtrips_needed(10000.0, 1000.0, 1.0) == 5
    assert roundtrips_needed(10000.0, 1000.0, 0.5) == 10

