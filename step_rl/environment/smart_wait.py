"""Smart wait with SPA render detection."""
import time
from typing import Dict, Tuple

from playwright.async_api import Page


async def smart_wait(page: Page, action_params: Dict, max_wait_ms: int = 5000) -> Tuple[bool, float]:
    """Wait intelligently for SPA stability or target element visibility.

    Returns:
        (success, elapsed_ms): success is True if the page stabilized or the
        target element became visible within max_wait_ms.
    """
    start = time.time()

    # 1. Fast check if element already exists
    element_id = action_params.get("element_id")
    if element_id:
        locator = page.locator(f"[data-testid='{element_id}']")
        try:
            await locator.wait_for(state="visible", timeout=500)
            return True, 0.0
        except Exception:
            pass

    # 2. SPA render detection
    spa_ready = await page.evaluate(
        """() => {
            if (window.__VUE__ || document.querySelector('[data-v-app]')) return 'vue';
            if (window.__REACT__ || document.querySelector('[data-reactroot]')) return 'react';
            return new Promise(resolve => {
                let lastHTML = document.body.innerHTML;
                let stable = 0;
                const check = () => {
                    if (document.body.innerHTML === lastHTML) {
                        if (++stable >= 3) return resolve('stable');
                    } else { stable = 0; lastHTML = document.body.innerHTML; }
                    setTimeout(check, 100);
                };
                check();
            });
        }"""
    )

    elapsed = (time.time() - start) * 1000
    if spa_ready and elapsed < max_wait_ms:
        return True, elapsed
    return False, elapsed
