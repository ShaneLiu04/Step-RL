"""Element fingerprint database for robust selector learning."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional


class ElementFingerprintDB:
    """Learn and store successful element selectors per domain."""

    def __init__(self, db_path: str = "./data/element_fingerprints.json"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fingerprints = defaultdict(lambda: defaultdict(list))
        self._load()

    def _extract_domain(self, url: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.netloc.lower()

    def _extract_pattern(self, action_params: Dict) -> Dict[str, Any]:
        """Extract selector pattern from action params."""
        pattern = {}
        if action_params.get("element_id"):
            pattern["type"] = "id"
            pattern["value"] = action_params["element_id"]
        elif action_params.get("element_text"):
            pattern["type"] = "text"
            pattern["value"] = action_params["element_text"]
        elif action_params.get("xpath"):
            pattern["type"] = "xpath"
            pattern["value"] = action_params["xpath"]
        elif action_params.get("css_selector"):
            pattern["type"] = "css"
            pattern["value"] = action_params["css_selector"]
        return pattern

    def record(
        self, url: str, action_params: Dict, success: bool, action_type: str = "click"
    ):
        if not success:
            return
        domain = self._extract_domain(url)
        pattern = self._extract_pattern(action_params)
        if pattern:
            self._fingerprints[domain][action_type].append(pattern)
        self._save()

    def suggest(
        self, url: str, action_type: str, target_text: str = ""
    ) -> Optional[Dict]:
        domain = self._extract_domain(url)
        patterns = self._fingerprints.get(domain, {}).get(action_type, [])
        if not patterns:
            return None

        # Find most frequent pattern type
        from collections import Counter

        type_counts = Counter(p["type"] for p in patterns)
        best_type = type_counts.most_common(1)[0][0]

        # Return the most common pattern of that type
        best_patterns = [p for p in patterns if p["type"] == best_type]
        return best_patterns[0] if best_patterns else None

    def _save(self):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(dict(self._fingerprints), f, ensure_ascii=False, indent=2)

    def _load(self):
        if self.db_path.exists():
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._fingerprints = defaultdict(lambda: defaultdict(list), data)

    def get_stats(self) -> Dict[str, Any]:
        """Return statistics about the fingerprint database."""
        stats = {}
        for domain, actions in self._fingerprints.items():
            stats[domain] = {
                action: len(patterns) for action, patterns in actions.items()
            }
        return stats
