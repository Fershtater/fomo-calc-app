"""Sentiment analysis service (CoinGecko integration)."""

import logging
from typing import Dict, List, Optional

from ..clients.coingecko import CoinGeckoClient

logger = logging.getLogger(__name__)


def map_hyperliquid_to_coingecko(symbol: str, coingecko_client: CoinGeckoClient) -> Optional[str]:
    """Map Hyperliquid symbol to CoinGecko coin ID.
    
    Args:
        symbol: Hyperliquid symbol (e.g., "BTC")
        coingecko_client: CoinGecko client instance
    
    Returns:
        CoinGecko coin ID (e.g., "bitcoin") or None if not found
    """
    return coingecko_client.find_coin_id(symbol)


def classify_sentiment_bias(sentiment_data: Optional[Dict]) -> str:
    """Classify sentiment bias from CoinGecko data.
    
    Args:
        sentiment_data: CoinGecko sentiment data (if available)
    
    Returns:
        "LONG", "SHORT", or "NEUTRAL"
    """
    if not sentiment_data:
        return "NEUTRAL"
    
    # Placeholder - implement actual sentiment analysis if needed
    # For now, return neutral
    return "NEUTRAL"


def build_sentiment_table(coins: List[Dict], coingecko_client: CoinGeckoClient) -> List[Dict]:
    """Build sentiment table for coins.
    
    Args:
        coins: List of coin data dicts
        coingecko_client: CoinGecko client instance
    
    Returns:
        List of sentiment data dicts
    """
    results = []
    for coin in coins:
        symbol = coin.get("coin", "")
        cg_id = map_hyperliquid_to_coingecko(symbol, coingecko_client)
        bias = classify_sentiment_bias(None)  # Placeholder
        
        results.append({
            "coin": symbol,
            "coingecko_id": cg_id,
            "bias": bias,
        })
    
    return results

