"""CoinGecko API client (optional sentiment data)."""

import logging
from typing import Dict, List, Optional

import httpx

from ..settings import Settings

logger = logging.getLogger(__name__)

COINGECKO_API = "https://api.coingecko.com/api/v3"


class CoinGeckoClient:
    """Client for CoinGecko API (optional sentiment data)."""
    
    def __init__(self, settings: Settings):
        """Initialize client with settings."""
        self.settings = settings
        self.client = httpx.Client(timeout=10.0)
        self._coins_list_cache: Optional[List[Dict]] = None
    
    def get_coins_list(self, use_cache: bool = True) -> List[Dict]:
        """Get list of all coins from CoinGecko (cached)."""
        if use_cache and self._coins_list_cache:
            return self._coins_list_cache
        
        try:
            response = self.client.get(f"{COINGECKO_API}/coins/list")
            response.raise_for_status()
            coins = response.json()
            self._coins_list_cache = coins
            logger.debug(f"Fetched {len(coins)} coins from CoinGecko")
            return coins
        except Exception as e:
            logger.warning(f"Error fetching CoinGecko coins list: {e}")
            return []
    
    def find_coin_id(self, symbol: str) -> Optional[str]:
        """Find CoinGecko coin ID for a symbol (e.g., 'BTC' -> 'bitcoin')."""
        coins = self.get_coins_list()
        symbol_upper = symbol.upper()
        
        # Try exact match first
        for coin in coins:
            if coin.get("symbol", "").upper() == symbol_upper:
                return coin.get("id")
        
        # Try name match
        for coin in coins:
            if coin.get("name", "").upper() == symbol_upper:
                return coin.get("id")
        
        logger.debug(f"Could not find CoinGecko ID for symbol {symbol}")
        return None

