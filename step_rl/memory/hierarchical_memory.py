"""Hierarchical state memory: episodic + semantic + abstraction layers."""

from collections import deque, defaultdict
from typing import Dict, List, Tuple, Any, Optional
import hashlib
import numpy as np


class StateAbstraction:
    """Abstract concrete DOM states into semantic templates."""

    def __init__(self):
        self.url_patterns = {
            r"/product[s]?/\d+": "product_detail",
            r"/cart": "cart_page",
            r"/checkout": "checkout_page",
            r"/search\?": "search_results",
            r"/login": "login_page",
        }

    def abstract_url(self, url: str) -> str:
        import re

        for pattern, abstract in self.url_patterns.items():
            if re.search(pattern, url):
                return abstract
        return "generic_page"

    def abstract_dom(self, dom_text: str) -> str:
        """Extract semantic features from DOM text."""
        features = []
        if "button" in dom_text.lower() or "btn" in dom_text.lower():
            features.append("has_button")
        if "input" in dom_text.lower() or "textbox" in dom_text.lower():
            features.append("has_input")
        if "search" in dom_text.lower():
            features.append("has_search")
        if "cart" in dom_text.lower() or "basket" in dom_text.lower():
            features.append("has_cart")
        return "|".join(features) if features else "empty"

    def abstract(self, url: str, dom_text: str) -> str:
        return f"{self.abstract_url(url)}|{self.abstract_dom(dom_text)}"


class HierarchicalStateMemory:
    """Dual-track memory: short-term episodic + long-term semantic."""

    def __init__(self, max_episodic: int = 200, max_semantic: int = 1000):
        # Short-term episodic memory (current episode loop detection)
        self.episodic_buffer = deque(maxlen=max_episodic)

        # Long-term semantic memory (cross-episode value storage)
        self.semantic_memory = {}
        self.max_semantic = max_semantic

        # Abstraction layer
        self.abstraction = StateAbstraction()

        # Q-learning parameters for semantic memory
        self.q_lr = 0.1
        self.q_gamma = 0.95

    def update(
        self, state_hash: str, url: str, dom_text: str, action: str, reward: float
    ) -> Dict[str, Any]:
        info = {}

        # 1. Episodic memory update (loop detection)
        self.episodic_buffer.append(state_hash)

        # 2. Semantic abstraction and Q-value update
        abstract_state = self.abstraction.abstract(url, dom_text)
        key = f"{abstract_state}|{action}"

        if key not in self.semantic_memory:
            self.semantic_memory[key] = {"q": 0.0, "count": 0, "avg_reward": 0.0}

        mem = self.semantic_memory[key]
        mem["count"] += 1

        # TD update for Q-value
        old_q = mem["q"]
        mem["avg_reward"] = (
            mem["avg_reward"] + (reward - mem["avg_reward"]) / mem["count"]
        )
        mem["q"] = old_q + self.q_lr * (reward + self.q_gamma * old_q - old_q)

        info["semantic_q"] = mem["q"]
        info["semantic_count"] = mem["count"]

        # Semantic novelty bonus (first time seeing this abstract state-action)
        if mem["count"] == 1:
            info["semantic_novelty_bonus"] = 0.05

        # 3. Episodic loop detection
        recent = list(self.episodic_buffer)[-5:]
        loop_count = recent.count(state_hash) - 1
        if loop_count > 0:
            info["episodic_loop_penalty"] = -0.1 * loop_count

        return info

    def get_semantic_value(self, url: str, dom_text: str, action: str) -> float:
        """Get Q-value for a state-action pair from semantic memory."""
        abstract_state = self.abstraction.abstract(url, dom_text)
        key = f"{abstract_state}|{action}"
        return self.semantic_memory.get(key, {}).get("q", 0.0)

    def reset_episodic(self):
        """Reset episodic buffer (call at start of new episode)."""
        self.episodic_buffer.clear()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "episodic_size": len(self.episodic_buffer),
            "semantic_size": len(self.semantic_memory),
            "avg_q_value": (
                np.mean([m["q"] for m in self.semantic_memory.values()])
                if self.semantic_memory
                else 0.0
            ),
        }
