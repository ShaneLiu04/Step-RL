"""Grounding validation result cache."""
import hashlib
import json
import time
from typing import Any, Dict, Optional


class GroundingCache:
    """TTL cache for grounding validation results, keyed by URL + action params."""

    def __init__(self, ttl_seconds: float = 5.0, max_size: int = 1000):
        self.cache: Dict[str, tuple[Any, float]] = {}
        self.ttl = ttl_seconds
        self.max_size = max_size

    def _key(self, page_url: str, action_params: Dict) -> str:
        url_hash = hashlib.md5(page_url.encode()).hexdigest()
        params_hash = hashlib.md5(json.dumps(action_params, sort_keys=True).encode()).hexdigest()
        return f"{url_hash}_{params_hash}"

    def get(self, page_url: str, action_params: Dict) -> Optional[Any]:
        key = self._key(page_url, action_params)
        if key in self.cache:
            result, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return result
            del self.cache[key]
        return None

    def set(self, page_url: str, action_params: Dict, result: Any):
        self.cache[self._key(page_url, action_params)] = (result, time.time())
        # Simple size-based eviction (oldest first)
        if len(self.cache) > self.max_size:
            oldest = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest]

    def invalidate_url(self, url: str):
        """Remove all cached entries for a given page URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        prefix = f"{url_hash}_"
        self.cache = {k: v for k, v in self.cache.items() if not k.startswith(prefix)}
