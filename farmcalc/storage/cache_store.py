"""File-based cache for external API data."""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CacheStore:
    """Simple file-based cache with TTL."""
    
    def __init__(self, cache_path: Path, ttl_sec: float):
        """Initialize cache with path and TTL."""
        self.cache_path = cache_path
        self.ttl_sec = ttl_sec
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None if not found/expired
        """
        if not self.cache_path.exists():
            return None
        
        try:
            with open(self.cache_path, "r") as f:
                cache_data = json.load(f)
            
            entry = cache_data.get(key)
            if not entry:
                return None
            
            # Check TTL
            cached_time = entry.get("timestamp", 0)
            if time.time() - cached_time > self.ttl_sec:
                logger.debug(f"Cache entry {key} expired")
                return None
            
            return entry.get("value")
        except Exception as e:
            logger.warning(f"Error reading cache: {e}")
            return None
    
    def set(self, key: str, value: Any):
        """Set cached value with current timestamp.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        cache_data = {}
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r") as f:
                    cache_data = json.load(f)
            except Exception:
                cache_data = {}
        
        cache_data[key] = {
            "value": value,
            "timestamp": time.time(),
        }
        
        try:
            with open(self.cache_path, "w") as f:
                json.dump(cache_data, f, indent=2)
            logger.debug(f"Cached {key}")
        except Exception as e:
            logger.warning(f"Error writing cache: {e}")

