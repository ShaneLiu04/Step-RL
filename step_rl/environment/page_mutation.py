"""Page mutation detection and DOM structure similarity matching."""

import hashlib
from typing import Dict, List, Optional, Tuple

from playwright.async_api import Page

from step_rl.utils.logging_utils import get_logger

logger = get_logger(__name__)


class PageMutationDetector:
    """Detect page mutations and find structurally similar elements."""

    def __init__(self):
        self._last_dom_hash = None
        self._last_url = None

    async def detect_mutation(self, page: Page) -> bool:
        """Check if page DOM has changed significantly."""
        current_url = page.url
        if current_url != self._last_url:
            self._last_url = current_url
            self._last_dom_hash = None
            return True

        current_dom = await page.content()
        current_hash = hashlib.md5(current_dom.encode()).hexdigest()

        if self._last_dom_hash and current_hash != self._last_dom_hash:
            self._last_dom_hash = current_hash
            return True

        self._last_dom_hash = current_hash
        return False

    async def find_similar_element(
        self, page: Page, original_selector: str, original_text: str = ""
    ) -> Optional[Dict]:
        """Find structurally similar element when original selector fails."""
        # Strategy 1: Try to find by similar text content
        if original_text:
            try:
                candidates = await page.locator(f"text={original_text}").all()
                if candidates:
                    return {"method": "text_similarity", "text": original_text}
            except Exception as e:
                logger.debug(f"Text similarity search failed: {e}")

        # Strategy 2: Try partial selector match (e.g., remove dynamic suffix from ID)
        if "[" in original_selector:
            # Try to match by partial attribute
            base = original_selector.split("[")[0]
            if base:
                try:
                    count = await page.locator(base).count()
                    if count > 0:
                        return {"method": "partial_selector", "selector": base}
                except Exception as e:
                    logger.debug(f"Partial selector search failed: {e}")

        return None

    def reset(self, url: str = ""):
        """Reset internal state for a new URL."""
        self._last_url = url
        self._last_dom_hash = None
