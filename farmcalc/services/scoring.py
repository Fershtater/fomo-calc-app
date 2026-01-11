"""Score-based safe entry evaluation with explainability."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..models.domain import WatchConfig

logger = logging.getLogger(__name__)


@dataclass
class ScoreComponents:
    """Individual score components."""
    spread_score: float
    mark_dev_score: float
    oracle_dev_score: float
    funding_score: float
    liquidity_score: float
    depth_score: float


@dataclass
class ScoreWeights:
    """Weights for score components."""
    spread: float = 0.25
    mark_dev: float = 0.20
    oracle_dev: float = 0.20
    funding: float = 0.15
    liquidity: float = 0.10
    depth: float = 0.10


@dataclass
class ScoreThresholds:
    """Thresholds for scoring."""
    # Bad thresholds (score = 0)
    spread_bad_bps: float = 10.0
    mark_bad_bps: float = 20.0
    oracle_bad_bps: float = 30.0
    funding_bad: float = 0.0001  # hourly
    liq_bad: float = 100000.0  # 24h volume
    depth_bad: float = 1000.0  # top-of-book depth
    
    # Good thresholds (score = 100)
    spread_good_bps: float = 1.0
    mark_good_bps: float = 2.0
    oracle_good_bps: float = 5.0
    funding_good: float = 0.00001
    liq_good: float = 10000000.0  # 24h volume
    depth_good: float = 10000.0  # top-of-book depth


@dataclass
class SafeEntryScore:
    """Complete safe entry score with explainability."""
    total_score: float
    component_scores: ScoreComponents
    metrics: Dict
    passed: bool
    reasons: List[str]
    threshold: float = 80.0


def calculate_spread_bps(best_bid: float, best_ask: float) -> float:
    """Calculate spread in basis points.
    
    Args:
        best_bid: Best bid price
        best_ask: Best ask price
    
    Returns:
        Spread in basis points
    """
    mid = (best_bid + best_ask) / 2.0
    if mid <= 0:
        return 9999.0
    spread = best_ask - best_bid
    return (spread / mid) * 10000


def calculate_mark_deviation_bps(mark_px: float, mid_px: float) -> float:
    """Calculate mark-mid deviation in basis points.
    
    Args:
        mark_px: Mark price
        mid_px: Mid price
    
    Returns:
        Deviation in basis points
    """
    if mid_px <= 0:
        return 9999.0
    return abs(mark_px - mid_px) / mid_px * 10000


def calculate_oracle_deviation_bps(oracle_px: float, mid_px: float) -> float:
    """Calculate oracle-mid deviation in basis points.
    
    Args:
        oracle_px: Oracle price
        mid_px: Mid price
    
    Returns:
        Deviation in basis points
    """
    if mid_px <= 0:
        return 9999.0
    return abs(oracle_px - mid_px) / mid_px * 10000


def _linear_score(value: float, good_threshold: float, bad_threshold: float) -> float:
    """Calculate linear score between good (100) and bad (0) thresholds.
    
    Args:
        value: Current value
        good_threshold: Value at which score = 100
        bad_threshold: Value at which score = 0
    
    Returns:
        Score between 0 and 100
    """
    if value <= good_threshold:
        return 100.0
    if value >= bad_threshold:
        return 0.0
    
    # Linear interpolation
    ratio = (value - good_threshold) / (bad_threshold - good_threshold)
    return 100.0 * (1.0 - ratio)


def _reverse_linear_score(value: float, good_threshold: float, bad_threshold: float) -> float:
    """Calculate reverse linear score (higher is better).
    
    Args:
        value: Current value
        good_threshold: Value at which score = 100
        bad_threshold: Value at which score = 0
    
    Returns:
        Score between 0 and 100
    """
    if value >= good_threshold:
        return 100.0
    if value <= bad_threshold:
        return 0.0
    
    # Linear interpolation
    ratio = (value - bad_threshold) / (good_threshold - bad_threshold)
    return 100.0 * ratio


def calculate_component_scores(
    spread_bps: float,
    mark_dev_bps: float,
    oracle_dev_bps: float,
    funding_abs: float,
    liquidity: float,
    depth_top: float,
    thresholds: ScoreThresholds,
) -> ScoreComponents:
    """Calculate individual score components.
    
    Args:
        spread_bps: Spread in basis points
        mark_dev_bps: Mark deviation in basis points
        oracle_dev_bps: Oracle deviation in basis points
        funding_abs: Absolute funding rate (hourly)
        liquidity: 24h volume
        depth_top: Top-of-book depth
        thresholds: Score thresholds
    
    Returns:
        ScoreComponents with individual scores
    """
    spread_score = _linear_score(
        spread_bps, thresholds.spread_good_bps, thresholds.spread_bad_bps
    )
    mark_dev_score = _linear_score(
        mark_dev_bps, thresholds.mark_good_bps, thresholds.mark_bad_bps
    )
    oracle_dev_score = _linear_score(
        oracle_dev_bps, thresholds.oracle_good_bps, thresholds.oracle_bad_bps
    )
    funding_score = _linear_score(
        funding_abs, thresholds.funding_good, thresholds.funding_bad
    )
    liquidity_score = _reverse_linear_score(
        liquidity, thresholds.liq_good, thresholds.liq_bad
    )
    depth_score = _reverse_linear_score(
        depth_top, thresholds.depth_good, thresholds.depth_bad
    )
    
    return ScoreComponents(
        spread_score=spread_score,
        mark_dev_score=mark_dev_score,
        oracle_dev_score=oracle_dev_score,
        funding_score=funding_score,
        liquidity_score=liquidity_score,
        depth_score=depth_score,
    )


def calculate_total_score(
    components: ScoreComponents,
    weights: ScoreWeights,
) -> float:
    """Calculate weighted total score.
    
    Args:
        components: Individual score components
        weights: Weights for each component
    
    Returns:
        Total score (0-100)
    """
    total = (
        components.spread_score * weights.spread +
        components.mark_dev_score * weights.mark_dev +
        components.oracle_dev_score * weights.oracle_dev +
        components.funding_score * weights.funding +
        components.liquidity_score * weights.liquidity +
        components.depth_score * weights.depth
    )
    return round(total, 2)


def _get_limiting_factors(
    components: ScoreComponents,
    metrics: Dict,
    threshold: float,
) -> List[str]:
    """Identify top limiting factors (lowest scores).
    
    Args:
        components: Score components
        metrics: Raw metrics
        threshold: Pass threshold
    
    Returns:
        List of reason strings
    """
    factors = []
    
    if components.spread_score < threshold:
        factors.append(f"spread high ({metrics.get('spread_bps', 0):.2f} bps)")
    if components.mark_dev_score < threshold:
        factors.append(f"mark deviation high ({metrics.get('mark_dev_bps', 0):.2f} bps)")
    if components.oracle_dev_score < threshold:
        factors.append(f"oracle deviation high ({metrics.get('oracle_dev_bps', 0):.2f} bps)")
    if components.funding_score < threshold:
        factors.append(f"funding high ({metrics.get('funding_abs', 0):.6f})")
    if components.liquidity_score < threshold:
        factors.append(f"liquidity low (${metrics.get('liquidity', 0):,.0f})")
    if components.depth_score < threshold:
        factors.append(f"depth low (${metrics.get('depth_top', 0):,.0f})")
    
    # Sort by score (lowest first) and return top 3
    score_map = {
        "spread": components.spread_score,
        "mark_dev": components.mark_dev_score,
        "oracle_dev": components.oracle_dev_score,
        "funding": components.funding_score,
        "liquidity": components.liquidity_score,
        "depth": components.depth_score,
    }
    
    sorted_factors = sorted(
        [(k, v) for k, v in score_map.items() if v < threshold],
        key=lambda x: x[1]
    )[:3]
    
    reasons = []
    for factor, score in sorted_factors:
        if factor == "spread":
            reasons.append(f"spread high ({metrics.get('spread_bps', 0):.2f} bps, score: {score:.1f})")
        elif factor == "mark_dev":
            reasons.append(f"mark deviation high ({metrics.get('mark_dev_bps', 0):.2f} bps, score: {score:.1f})")
        elif factor == "oracle_dev":
            reasons.append(f"oracle deviation high ({metrics.get('oracle_dev_bps', 0):.2f} bps, score: {score:.1f})")
        elif factor == "funding":
            reasons.append(f"funding high ({metrics.get('funding_abs', 0):.6f}, score: {score:.1f})")
        elif factor == "liquidity":
            reasons.append(f"liquidity low (${metrics.get('liquidity', 0):,.0f}, score: {score:.1f})")
        elif factor == "depth":
            reasons.append(f"depth low (${metrics.get('depth_top', 0):,.0f}, score: {score:.1f})")
    
    return reasons[:3]


def _calculate_depth_top(l2_book: Dict, top_k: int = 3) -> float:
    """Calculate top-of-book depth from L2 book.
    
    Args:
        l2_book: L2 book data
        top_k: Number of levels to sum
    
    Returns:
        Total depth (bid + ask)
    """
    # Try to extract depth from various possible structures
    depth = 0.0
    
    # If we have levels structure
    if "levels" in l2_book:
        levels = l2_book["levels"]
        if isinstance(levels, list) and len(levels) >= 2:
            bids = levels[0] if isinstance(levels[0], list) else []
            asks = levels[1] if isinstance(levels[1], list) else []
            
            for i in range(min(top_k, len(bids))):
                if isinstance(bids[i], (list, tuple)) and len(bids[i]) >= 2:
                    depth += float(bids[i][1])  # size is second element
                elif isinstance(bids[i], dict):
                    depth += float(bids[i].get("sz", 0))
            
            for i in range(min(top_k, len(asks))):
                if isinstance(asks[i], (list, tuple)) and len(asks[i]) >= 2:
                    depth += float(asks[i][1])
                elif isinstance(asks[i], dict):
                    depth += float(asks[i].get("sz", 0))
    
    # Fallback: use a default if depth not available
    if depth == 0.0:
        depth = 5000.0  # Default assumption
    
    return depth


def evaluate_safe_entry(
    coin: str,
    coin_data: Dict,
    l2_book: Optional[Dict],
    config: WatchConfig,
    score_threshold: float = 80.0,
    weights: Optional[ScoreWeights] = None,
    thresholds: Optional[ScoreThresholds] = None,
) -> Optional[SafeEntryScore]:
    """Evaluate safe entry with score-based system.
    
    Args:
        coin: Coin symbol
        coin_data: Coin market data dict
        l2_book: L2 book data with best_bid, best_ask, etc.
        config: Watch configuration
        score_threshold: Minimum score to pass (default 80.0)
        weights: Score weights (uses defaults if None)
        thresholds: Score thresholds (uses defaults if None)
    
    Returns:
        SafeEntryScore with explainability, or None if invalid data
    """
    if not l2_book:
        return None
    
    best_bid = l2_book.get("best_bid", 0)
    best_ask = l2_book.get("best_ask", 0)
    mid = l2_book.get("mid", 0)
    
    if mid <= 0:
        return None
    
    mark_px = coin_data.get("markPx", 0)
    oracle_px = coin_data.get("oraclePx", 0)
    funding = coin_data.get("funding", 0)
    day_ntl_vlm = coin_data.get("dayNtlVlm", 0)
    
    # Adjust funding for funding_kind
    funding_hourly = funding
    if config.funding_kind == "8h":
        funding_hourly = funding / 8.0
    
    # Calculate metrics
    spread_bps = calculate_spread_bps(best_bid, best_ask)
    mark_dev_bps = calculate_mark_deviation_bps(mark_px, mid)
    oracle_dev_bps = calculate_oracle_deviation_bps(oracle_px, mid)
    funding_abs = abs(funding_hourly)
    liquidity = day_ntl_vlm
    depth_top = _calculate_depth_top(l2_book, top_k=3)
    
    # Use defaults if not provided
    if weights is None:
        weights = ScoreWeights()
    if thresholds is None:
        thresholds = ScoreThresholds()
    
    # Calculate component scores
    components = calculate_component_scores(
        spread_bps, mark_dev_bps, oracle_dev_bps,
        funding_abs, liquidity, depth_top, thresholds
    )
    
    # Calculate total score
    total_score = calculate_total_score(components, weights)
    
    # Build metrics dict
    metrics = {
        "spread_bps": spread_bps,
        "mark_dev_bps": mark_dev_bps,
        "oracle_dev_bps": oracle_dev_bps,
        "funding": funding,
        "funding_abs": funding_abs,
        "funding_hourly": funding_hourly,
        "liquidity": liquidity,
        "depth_top": depth_top,
        "mark_px": mark_px,
        "mid_px": mid,
        "oracle_px": oracle_px,
        "best_bid": best_bid,
        "best_ask": best_ask,
    }
    
    # Determine if passed
    passed = total_score >= score_threshold
    
    # Get limiting factors
    reasons = _get_limiting_factors(components, metrics, score_threshold) if not passed else []
    
    # If passed, add positive reasons
    if passed:
        reasons = []
        if components.spread_score >= score_threshold:
            reasons.append("spread ok")
        if components.mark_dev_score >= score_threshold:
            reasons.append("mark ok")
        if components.oracle_dev_score >= score_threshold:
            reasons.append("oracle ok")
        if components.funding_score >= score_threshold:
            reasons.append("funding ok")
        if components.liquidity_score >= score_threshold:
            reasons.append("liquidity ok")
        if components.depth_score >= score_threshold:
            reasons.append("depth ok")
    
    # Calculate safe sides with limit prices (if passed)
    safe_sides = []
    if passed:
        from .pricing import suggested_limit_prices
        
        if config.side in ["long", "either"]:
            open_limit, close_limit = suggested_limit_prices(
                "LONG", best_bid, best_ask,
                config.open_offset_bps, config.close_offset_bps
            )
            safe_sides.append({
                "side": "LONG",
                "open_limit_px": open_limit,
                "close_limit_px": close_limit,
                "best_bid": best_bid,
                "best_ask": best_ask,
            })
        
        if config.side in ["short", "either"]:
            open_limit, close_limit = suggested_limit_prices(
                "SHORT", best_bid, best_ask,
                config.open_offset_bps, config.close_offset_bps
            )
            safe_sides.append({
                "side": "SHORT",
                "open_limit_px": open_limit,
                "close_limit_px": close_limit,
                "best_bid": best_bid,
                "best_ask": best_ask,
            })
    
    # Add safe_sides to metrics for compatibility
    metrics["safe_sides"] = safe_sides
    
    return SafeEntryScore(
        total_score=total_score,
        component_scores=components,
        metrics=metrics,
        passed=passed,
        reasons=reasons,
        threshold=score_threshold,
    )
