"""Tests for fill probability estimation."""

import pytest

from farmcalc.services.fill_model import (
    FillModelService,
    estimate_fill_probability,
    update_calibration_from_feedback,
)


def test_estimate_fill_probability_basic():
    """Test basic fill probability estimation."""
    prob = estimate_fill_probability(
        spread_bps=2.0,
        depth_top=10000.0,
        notional_size=1000.0,
        offset_bps=10.0,
    )
    
    assert 0.0 <= prob <= 1.0


def test_fill_probability_increases_with_offset():
    """Test that more aggressive offset increases fill probability."""
    prob_low = estimate_fill_probability(
        spread_bps=2.0,
        depth_top=10000.0,
        notional_size=1000.0,
        offset_bps=0.0,
    )
    
    prob_high = estimate_fill_probability(
        spread_bps=2.0,
        depth_top=10000.0,
        notional_size=1000.0,
        offset_bps=50.0,
    )
    
    assert prob_high >= prob_low


def test_fill_probability_decreases_with_spread():
    """Test that wider spread decreases fill probability."""
    prob_tight = estimate_fill_probability(
        spread_bps=1.0,
        depth_top=10000.0,
        notional_size=1000.0,
        offset_bps=10.0,
    )
    
    prob_wide = estimate_fill_probability(
        spread_bps=10.0,
        depth_top=10000.0,
        notional_size=1000.0,
        offset_bps=10.0,
    )
    
    assert prob_tight >= prob_wide


def test_fill_probability_increases_with_depth():
    """Test that deeper book increases fill probability."""
    prob_shallow = estimate_fill_probability(
        spread_bps=2.0,
        depth_top=1000.0,
        notional_size=1000.0,
        offset_bps=10.0,
    )
    
    prob_deep = estimate_fill_probability(
        spread_bps=2.0,
        depth_top=10000.0,
        notional_size=1000.0,
        offset_bps=10.0,
    )
    
    assert prob_deep >= prob_shallow


def test_fill_model_service():
    """Test FillModelService."""
    service = FillModelService()
    
    # Add snapshots
    service.add_snapshot("BTC", {"mid": 100.0, "bid": 99.99, "ask": 100.01, "spread": 2.0, "depth_top": 5000.0})
    service.add_snapshot("BTC", {"mid": 100.1, "bid": 100.09, "ask": 100.11, "spread": 2.0, "depth_top": 5000.0})
    
    # Estimate probability
    prob = service.estimate_fill_prob(
        coin="BTC",
        spread_bps=2.0,
        depth_top=5000.0,
        notional_size=1000.0,
        offset_bps=10.0,
    )
    
    assert 0.0 <= prob <= 1.0
    
    # Record feedback
    service.record_feedback("BTC", "open", True)
    
    # Should still return valid probability
    prob2 = service.estimate_fill_prob(
        coin="BTC",
        spread_bps=2.0,
        depth_top=5000.0,
        notional_size=1000.0,
        offset_bps=10.0,
    )
    
    assert 0.0 <= prob2 <= 1.0


def test_update_calibration_from_feedback():
    """Test calibration update from feedback."""
    from farmcalc.services.fill_model import FillHistory
    
    history = FillHistory(coin="BTC")
    
    # Record some feedback
    calibration1 = update_calibration_from_feedback(history, "open", True)
    calibration2 = update_calibration_from_feedback(history, "open", True)
    calibration3 = update_calibration_from_feedback(history, "open", False)
    
    # Calibration should adjust based on observed rate
    assert history.filled_count == 2
    assert history.missed_count == 1
    assert 0.0 <= calibration3.base_prob <= 1.0

