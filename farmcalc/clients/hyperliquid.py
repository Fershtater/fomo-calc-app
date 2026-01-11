"""Hyperliquid API client."""

import logging
from typing import Dict, List, Optional, Tuple

import httpx

from ..settings import Settings

logger = logging.getLogger(__name__)


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
            
            # Try different possible response structures
            universe = data.get("universe", [])
            
            # Asset contexts might be in different locations
            asset_contexts = []
            if "meta" in data and isinstance(data["meta"], dict):
                asset_contexts = data["meta"].get("assetContexts", [])
            elif "assetContexts" in data:
                asset_contexts = data["assetContexts"]
            elif isinstance(data.get("meta"), list):
                asset_contexts = data["meta"]
            
            if not universe or not asset_contexts:
                logger.warning(
                    f"Unexpected API response structure. Universe: {len(universe)}, Contexts: {len(asset_contexts)}"
                )
            
            return universe, asset_contexts
        except Exception as e:
            logger.error(f"Error fetching market data: {e}")
            raise
    
    def get_coin_data(self, coin: str) -> Optional[Dict]:
        """Get market data for a specific coin."""
        universe, contexts = self.fetch_market_data()
        
        for i, u in enumerate(universe):
            if u.get("name") == coin:
                if i < len(contexts):
                    ctx = contexts[i]
                    return {
                        "coin": coin,
                        "maxLeverage": u.get("maxLeverage", 0),
                        "onlyIsolated": u.get("onlyIsolated", False),
                        "marginMode": u.get("marginMode"),
                        "funding": ctx.get("funding", {}).get("funding", 0),
                        "markPx": ctx.get("markPx", 0),
                        "midPx": ctx.get("midPx", 0),
                        "oraclePx": ctx.get("oraclePx", 0),
                        "openInterest": ctx.get("openInterest", 0),
                        "dayNtlVlm": ctx.get("dayNtlVlm", 0),
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
                coins.append({
                    "coin": coin_name,
                    "maxLeverage": u.get("maxLeverage", 0),
                    "onlyIsolated": u.get("onlyIsolated", False),
                    "marginMode": u.get("marginMode"),
                    "funding": ctx.get("funding", {}).get("funding", 0),
                    "markPx": ctx.get("markPx", 0),
                    "midPx": ctx.get("midPx", 0),
                    "oraclePx": ctx.get("oraclePx", 0),
                    "openInterest": ctx.get("openInterest", 0),
                    "dayNtlVlm": ctx.get("dayNtlVlm", 0),
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

