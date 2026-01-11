"""Tests for scoring functions."""

import pytest

from farmcalc.models.domain import WatchConfig, WatchThresholds
from farmcalc.services.scoring import (
    SafeEntryScore,
    ScoreComponents,
    ScoreThresholds,
    ScoreWeights,
    calculate_component_scores,
    calculate_mark_deviation_bps,
    calculate_oracle_deviation_bps,
    calculate_spread_bps,
    calculate_total_score,
    evaluate_safe_entry,
)


def test_calculate_spread_bps():
    """Test spread calculation."""
    spread = calculate_spread_bps(100.0, 100.1)
    assert spread == pytest.approx(10.0, rel=0.1)  # 0.1 / 100.05 * 10000


def test_calculate_mark_deviation_bps():
    """Test mark deviation calculation."""
    dev = calculate_mark_deviation_bps(100.05, 100.0)
    assert dev == pytest.approx(5.0, rel=0.1)


def test_calculate_oracle_deviation_bps():
    """Test oracle deviation calculation."""
    dev = calculate_oracle_deviation_bps(100.1, 100.0)
    assert dev == pytest.approx(10.0, rel=0.1)


def test_calculate_component_scores():
    """Test component score calculation."""
    thresholds = ScoreThresholds()
    components = calculate_component_scores(
        spread_bps=2.0,
        mark_dev_bps=3.0,
        oracle_dev_bps=5.0,
        funding_abs=0.00001,
        liquidity=5000000.0,
        depth_top=5000.0,
        thresholds=thresholds,
    )
    
    assert 0 <= components.spread_score <= 100
    assert 0 <= components.mark_dev_score <= 100
    assert 0 <= components.oracle_dev_score <= 100
    assert 0 <= components.funding_score <= 100
    assert 0 <= components.liquidity_score <= 100
    assert 0 <= components.depth_score <= 100


def test_calculate_total_score():
    """Test total score calculation."""
    components = ScoreComponents(
        spread_score=90.0,
        mark_dev_score=85.0,
        oracle_dev_score=80.0,
        funding_score=75.0,
        liquidity_score=70.0,
        depth_score=65.0,
    )
    weights = ScoreWeights()
    
    total = calculate_total_score(components, weights)
    assert 0 <= total <= 100
    assert total > 70  # Should be weighted average


def test_score_monotonicity():
    """Test that scores are monotonic (better metrics = higher scores)."""
    thresholds = ScoreThresholds()
    
    # Better spread should give higher score
    good = calculate_component_scores(1.0, 2.0, 5.0, 0.00001, 10000000, 10000, thresholds)
    bad = calculate_component_scores(10.0, 20.0, 30.0, 0.0001, 100000, 1000, thresholds)
    
    assert good.spread_score > bad.spread_score
    assert good.mark_dev_score > bad.mark_dev_score
    assert good.oracle_dev_score > bad.oracle_dev_score
    assert good.funding_score > bad.funding_score
    assert good.liquidity_score > bad.liquidity_score
    assert good.depth_score > bad.depth_score


def test_evaluate_safe_entry():
    """Test safe entry evaluation with scoring."""
    coin_data = {
        "markPx": 100.0,
        "oraclePx": 100.0,
        "funding": 0.00001,
        "dayNtlVlm": 10000000.0,
    }
    l2_book = {
        "best_bid": 99.99,
        "best_ask": 100.01,
        "mid": 100.0,
        "spread_bps": 2.0,
    }
    config = WatchConfig(
        thresholds=WatchThresholds(),
        funding_kind="hourly",
    )
    
    result = evaluate_safe_entry(coin="BTC", coin_data=coin_data, l2_book=l2_book, config=config)
    
    assert result is not None
    assert isinstance(result, SafeEntryScore)
    assert 0 <= result.total_score <= 100
    assert isinstance(result.component_scores, ScoreComponents)
    assert isinstance(result.metrics, dict)
    assert "reasons" in result.metrics or result.reasons is not None


def test_evaluate_safe_entry_fails():
    """Test that bad conditions fail evaluation."""
    coin_data = {
        "markPx": 100.0,
        "oraclePx": 100.0,
        "funding": 0.001,  # Very high funding
        "dayNtlVlm": 1000.0,  # Low liquidity
    }
    l2_book = {
        "best_bid": 99.0,
        "best_ask": 101.0,  # Wide spread
        "mid": 100.0,
        "spread_bps": 200.0,
    }
    config = WatchConfig(
        thresholds=WatchThresholds(),
        funding_kind="hourly",
    )
    
    result = evaluate_safe_entry(coin="BTC", coin_data=coin_data, l2_book=l2_book, config=config)
    
    # Should either fail or have low score
    if result:
        assert result.total_score < 50  # Low score for bad conditions
