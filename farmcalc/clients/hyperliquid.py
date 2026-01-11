"""Hyperliquid API client."""

import logging
from typing import Dict, List, Optional, Tuple

import httpx

from ..settings import Settings

logger = logging.getLogger(__name__)


def _extract_funding(ctx: Dict) -> float:
    """Extract funding value from context, handling different formats.
    
    Args:
        ctx: Context dict from Hyperliquid API
    
    Returns:
        Funding value as float (0.0 if not found or invalid)
    """
    if not isinstance(ctx, dict):
        return 0.0
    
    funding_field = ctx.get("funding")
    if isinstance(funding_field, dict):
        return float(funding_field.get("funding", 0))
    elif isinstance(funding_field, (int, float)):
        return float(funding_field)
    elif isinstance(funding_field, str):
        try:
            return float(funding_field)
        except (ValueError, TypeError):
            return 0.0
    
    return 0.0


def _extract_float(ctx: Dict, key: str, default: float = 0.0) -> float:
    """Extract float value from context, handling string/number formats.
    
    Args:
        ctx: Context dict from Hyperliquid API
        key: Key to extract
        default: Default value if not found or invalid
    
    Returns:
        Float value (default if not found or invalid)
    """
    if not isinstance(ctx, dict):
        return default
    
    value = ctx.get(key, default)
    if isinstance(value, (int, float)):
        return float(value)
    elif isinstance(value, str):
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    return default


class HyperliquidClient:
    """Client for Hyperliquid API."""
    
    def __init__(self, settings: Settings):
        """Initialize client with settings."""
        self.settings = settings
        self.client = httpx.Client(timeout=10.0)
    
    def fetch_market_data(self) -> Tuple[List[Dict], List[Dict]]:
        """Fetch universe and asset contexts from Hyperliquid API."""
        try:
            response = self.client.post(
                self.settings.hyperliquid_api_url,
                json={"type": "metaAndAssetCtxs"}
            )
            response.raise_for_status()
            data = response.json()
            
            # Hyperliquid API returns a list with two elements: [meta, assetContexts]
            # where meta is a dict with "universe" field, and assetContexts is a list
            universe = []
            asset_contexts = []
            
            if isinstance(data, list):
                # Response is a list: [meta_dict, assetContexts_list]
                if len(data) >= 2:
                    meta = data[0] if isinstance(data[0], dict) else {}
                    asset_contexts = data[1] if isinstance(data[1], list) else []
                    
                    # Extract universe from meta dict
                    universe = meta.get("universe", [])
                elif len(data) == 1 and isinstance(data[0], dict):
                    # Single dict response (shouldn't happen, but handle gracefully)
                    meta = data[0]
                    universe = meta.get("universe", [])
                    asset_contexts = meta.get("assetContexts", [])
            elif isinstance(data, dict):
                # Response is a dict (fallback for different API versions)
                universe = data.get("universe", [])
                
                # Asset contexts might be in different locations
                if "meta" in data and isinstance(data["meta"], dict):
                    universe = data["meta"].get("universe", universe)
                    asset_contexts = data["meta"].get("assetContexts", [])
                elif "assetContexts" in data:
                    asset_contexts = data["assetContexts"] if isinstance(data["assetContexts"], list) else []
                elif isinstance(data.get("meta"), list):
                    asset_contexts = data["meta"]
            
            if not universe or not asset_contexts:
                logger.warning(
                    f"Unexpected API response structure. Data type: {type(data)}, "
                    f"Universe: {len(universe)}, Contexts: {len(asset_contexts)}"
                )
            
            return universe, asset_contexts
        except Exception as e:
            logger.error(f"Error fetching market data: {e}", exc_info=True)
            raise
    
    def get_coin_data(self, coin: str) -> Optional[Dict]:
        """Get market data for a specific coin."""
        universe, contexts = self.fetch_market_data()
        
        for i, u in enumerate(universe):
            if u.get("name") == coin:
                if i < len(contexts):
                    ctx = contexts[i]
                    if not isinstance(ctx, dict):
                        continue
                    
                    return {
                        "coin": coin,
                        "maxLeverage": _extract_float(u, "maxLeverage", 0),
                        "onlyIsolated": u.get("onlyIsolated", False),
                        "marginMode": u.get("marginMode"),
                        "funding": _extract_funding(ctx),
                        "markPx": _extract_float(ctx, "markPx", 0),
                        "midPx": _extract_float(ctx, "midPx", 0),
                        "oraclePx": _extract_float(ctx, "oraclePx", 0),
                        "openInterest": _extract_float(ctx, "openInterest", 0),
                        "dayNtlVlm": _extract_float(ctx, "dayNtlVlm", 0),
                    }
        return None
    
    def get_all_coins(self) -> List[Dict]:
        """Get all coins with their market data."""
        universe, contexts = self.fetch_market_data()
        coins = []
        
        for i, u in enumerate(universe):
            coin_name = u.get("name")
            if coin_name and i < len(contexts):
                ctx = contexts[i]
                if not isinstance(ctx, dict):
                    continue
                
                coins.append({
                    "coin": coin_name,
                    "maxLeverage": _extract_float(u, "maxLeverage", 0),
                    "onlyIsolated": u.get("onlyIsolated", False),
                    "marginMode": u.get("marginMode"),
                    "funding": _extract_funding(ctx),
                    "markPx": _extract_float(ctx, "markPx", 0),
                    "midPx": _extract_float(ctx, "midPx", 0),
                    "oraclePx": _extract_float(ctx, "oraclePx", 0),
                    "openInterest": _extract_float(ctx, "openInterest", 0),
                    "dayNtlVlm": _extract_float(ctx, "dayNtlVlm", 0),
                })
        
        return coins
    
    def get_l2_book(self, coin: str) -> Optional[Dict]:
        """Fetch L2 order book for a coin and return best bid/ask."""
        try:
            response = self.client.post(
                self.settings.hyperliquid_api_url,
                json={"type": "l2Book", "coin": coin}
            )
            response.raise_for_status()
            data = response.json()
            
            # Parse best bid/ask
            from ..services.pricing import parse_best_bid_ask
            
            result = parse_best_bid_ask(data)
            if result:
                return result
            
            logger.warning(f"Could not parse L2 book structure for {coin}")
            return None
        except Exception as e:
            logger.error(f"Error fetching L2 book for {coin}: {e}")
            return None

