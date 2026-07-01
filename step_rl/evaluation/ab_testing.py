"""A/B testing framework for policy variants."""
import hashlib
import random
from typing import Dict, List, Any
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class VariantResult:
    variant: str
    episodes: int = 0
    successes: int = 0
    total_return: float = 0.0
    total_steps: int = 0


class ABTestFramework:
    """Route traffic to different policy variants and compare."""

    def __init__(self, variants: Dict[str, Any], traffic_split: Dict[str, float] = None):
        self.variants = variants
        self.traffic_split = traffic_split or {name: 1.0 / len(variants) for name in variants}
        self.results = {name: VariantResult(name) for name in variants}

    def select_variant(self, user_id: str) -> str:
        """Consistent hashing by user_id."""
        hash_val = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        cumulative = 0.0
        for name, weight in self.traffic_split.items():
            cumulative += weight
            if hash_val % 10000 / 10000 < cumulative:
                return name
        return list(self.variants.keys())[-1]

    def record_result(self, variant: str, success: bool, episode_return: float, steps: int):
        result = self.results[variant]
        result.episodes += 1
        if success:
            result.successes += 1
        result.total_return += episode_return
        result.total_steps += steps

    def get_stats(self) -> Dict[str, Dict[str, float]]:
        stats = {}
        for name, result in self.results.items():
            stats[name] = {
                "episodes": result.episodes,
                "success_rate": result.successes / max(result.episodes, 1),
                "avg_return": result.total_return / max(result.episodes, 1),
                "avg_steps": result.total_steps / max(result.episodes, 1),
            }
        return stats

    def is_significant(self, variant_a: str, variant_b: str, min_episodes: int = 100) -> bool:
        """Check if difference is statistically significant."""
        a = self.results[variant_a]
        b = self.results[variant_b]
        if a.episodes < min_episodes or b.episodes < min_episodes:
            return False

        # Simple proportion test
        p_a = a.successes / a.episodes
        p_b = b.successes / b.episodes
        p_pool = (a.successes + b.successes) / (a.episodes + b.episodes)
        se = (p_pool * (1 - p_pool) * (1/a.episodes + 1/b.episodes)) ** 0.5
        z = (p_a - p_b) / max(se, 1e-10)
        return abs(z) > 1.96  # 95% confidence
