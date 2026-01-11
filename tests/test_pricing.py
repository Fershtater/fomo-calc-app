"""Tests for pricing functions."""

import pytest

from farmcalc.services.pricing import (
    calculate_limit_price,
    clamp_maker_price,
    parse_best_bid_ask,
    suggested_limit_prices,
)


def test_parse_best_bid_ask_levels():
    """Test parsing L2 book with levels structure."""
    data = {
        "levels": [
            [[100.0, 1.0], [99.9, 2.0]],  # bids
            [[100.1, 1.0], [100.2, 2.0]],  # asks
        ]
    }
    result = parse_best_bid_ask(data)
    assert result is not None
    assert result["best_bid"] == 100.0
    assert result["best_ask"] == 100.1
    assert result["mid"] == 100.05


def test_parse_best_bid_ask_dict():
    """Test parsing L2 book with bids/asks dict."""
    data = {
        "bids": [[100.0, 1.0]],
        "asks": [[100.1, 1.0]],
    }
    result = parse_best_bid_ask(data)
    assert result is not None
    assert result["best_bid"] == 100.0
    assert result["best_ask"] == 100.1


def test_calculate_limit_price_long_open():
    """Test limit price for LONG open."""
    price = calculate_limit_price("LONG", 100.0, 100.1, 10.0, "open")
    assert price <= 100.0  # Must be <= best_bid for maker


def test_calculate_limit_price_short_open():
    """Test limit price for SHORT open."""
    price = calculate_limit_price("SHORT", 100.0, 100.1, 10.0, "open")
    assert price >= 100.1  # Must be >= best_ask for maker


def test_clamp_maker_price():
    """Test maker price clamping."""
    # LONG open must be <= best_bid
    clamped = clamp_maker_price(100.5, 100.0, 100.1, "LONG", "open")
    assert clamped == 100.0
    
    # SHORT open must be >= best_ask
    clamped = clamp_maker_price(100.0, 100.0, 100.1, "SHORT", "open")
    assert clamped == 100.1


def test_suggested_limit_prices():
    """Test suggested limit prices."""
    open_limit, close_limit = suggested_limit_prices("LONG", 100.0, 100.1, 0.0, 0.0)
    assert open_limit <= 100.0
    assert close_limit >= 100.1

