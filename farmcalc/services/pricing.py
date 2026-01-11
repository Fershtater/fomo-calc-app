"""Pricing functions for limit orders and L2 book parsing."""

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def parse_best_bid_ask(data: Dict) -> Optional[Dict]:
    """Parse best bid/ask from L2 book response.
    
    Supports multiple response structure variants.
    
    Args:
        data: L2 book response data
    
    Returns:
        Dict with best_bid, best_ask, mid, spread, spread_bps, or None if parsing fails
    """
    best_bid = None
    best_ask = None
    
    if isinstance(data, dict):
        # Try different possible structures
        if "levels" in data:
            levels = data["levels"]
            if isinstance(levels, list) and len(levels) >= 2:
                bids = levels[0] if isinstance(levels[0], list) else []
                asks = levels[1] if isinstance(levels[1], list) else []
                if bids:
                    best_bid = float(bids[0][0]) if isinstance(bids[0], (list, tuple)) else float(bids[0].get("px", 0))
                if asks:
                    best_ask = float(asks[0][0]) if isinstance(asks[0], (list, tuple)) else float(asks[0].get("px", 0))
        elif "bids" in data and "asks" in data:
            bids = data["bids"]
            asks = data["asks"]
            if bids:
                best_bid = float(bids[0][0]) if isinstance(bids[0], (list, tuple)) else float(bids[0].get("px", 0))
            if asks:
                best_ask = float(asks[0][0]) if isinstance(asks[0], (list, tuple)) else float(asks[0].get("px", 0))
        elif "book" in data:
            book = data["book"]
            if isinstance(book, dict):
                bids = book.get("bids", [])
                asks = book.get("asks", [])
                if bids:
                    best_bid = float(bids[0][0]) if isinstance(bids[0], (list, tuple)) else float(bids[0].get("px", 0))
                if asks:
                    best_ask = float(asks[0][0]) if isinstance(asks[0], (list, tuple)) else float(asks[0].get("px", 0))
    
    if best_bid is None or best_ask is None:
        return None
    
    mid = (best_bid + best_ask) / 2.0
    spread = best_ask - best_bid
    spread_bps = (spread / mid) * 10000 if mid > 0 else 0
    
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread": spread,
        "spread_bps": spread_bps,
    }


def clamp_maker_price(price: float, best_bid: float, best_ask: float, side: str, order_type: str) -> float:
    """Clamp a limit price to be maker-safe.
    
    Args:
        price: Proposed limit price
        best_bid: Current best bid
        best_ask: Current best ask
        side: "LONG" or "SHORT"
        order_type: "open" or "close"
    
    Returns:
        Clamped maker-safe price
    """
    if side.upper() == "LONG":
        if order_type == "open":
            # LONG open = BUY -> must be <= best_bid
            return min(price, best_bid)
        else:  # close
            # LONG close = SELL -> must be >= best_ask
            return max(price, best_ask)
    else:  # SHORT
        if order_type == "open":
            # SHORT open = SELL -> must be >= best_ask
            return max(price, best_ask)
        else:  # close
            # SHORT close = BUY -> must be <= best_bid
            return min(price, best_bid)


def calculate_limit_price(
    side: str,
    best_bid: float,
    best_ask: float,
    offset_bps: float,
    order_type: str,  # "open" or "close"
) -> float:
    """Calculate limit price with offset, ensuring maker-safe.
    
    Args:
        side: "LONG" or "SHORT"
        best_bid: Best bid price
        best_ask: Best ask price
        offset_bps: Offset in basis points (e.g., 10 = 0.1%)
        order_type: "open" or "close"
    
    Returns:
        Maker-safe limit price
    """
    offset_mult = 1.0 - (offset_bps / 10000.0) if offset_bps >= 0 else 1.0 + (abs(offset_bps) / 10000.0)
    
    if side.upper() == "LONG":
        if order_type == "open":
            # LONG open = BUY -> use best_bid * (1 - offset)
            limit_px = best_bid * offset_mult
        else:  # close
            # LONG close = SELL -> use best_ask * (1 + offset)
            limit_px = best_ask * (1.0 + (offset_bps / 10000.0))
    else:  # SHORT
        if order_type == "open":
            # SHORT open = SELL -> use best_ask * (1 + offset)
            limit_px = best_ask * (1.0 + (offset_bps / 10000.0))
        else:  # close
            # SHORT close = BUY -> use best_bid * (1 - offset)
            limit_px = best_bid * offset_mult
    
    # Clamp to ensure maker-safe
    return clamp_maker_price(limit_px, best_bid, best_ask, side, order_type)


def suggested_limit_prices(
    side: str,
    best_bid: float,
    best_ask: float,
    open_offset_bps: float,
    close_offset_bps: float,
) -> Tuple[float, float]:
    """Calculate suggested open and close limit prices.
    
    Args:
        side: "LONG" or "SHORT"
        best_bid: Best bid price
        best_ask: Best ask price
        open_offset_bps: Open limit price offset in basis points
        close_offset_bps: Close limit price offset in basis points
    
    Returns:
        Tuple of (open_limit_px, close_limit_px)
    """
    open_limit = calculate_limit_price(side, best_bid, best_ask, open_offset_bps, "open")
    close_limit = calculate_limit_price(side, best_bid, best_ask, close_offset_bps, "close")
    return open_limit, close_limit

