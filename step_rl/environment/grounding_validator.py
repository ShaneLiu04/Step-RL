"""
Grounding Signal v2.0
- Pre-execution validation
- Multi-attribute robust anchoring with input sanitization (via shared locator)
- Smart auto-correction suggestions
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import Locator, Page

from step_rl.environment.element_fingerprint import ElementFingerprintDB
from step_rl.environment.page_mutation import PageMutationDetector
from step_rl.environment.locator import (
    robust_locate,
    remove_dynamic_suffix,
    find_similar_by_structure,
)
from step_rl.utils.logging_utils import get_logger
from step_rl.environment.grounding_cache import GroundingCache
from step_rl.utils.security_utils import escape_xpath_string

logger = get_logger(__name__)


@dataclass
class GroundingResult:
    valid: bool = False
    reward: float = 0.0
    corrected_action: Optional[Dict[str, Any]] = None
    message: str = ""
    locator: Optional[Locator] = None
    match_info: Optional[Dict[str, Any]] = None


@dataclass
class ElementCandidate:
    locator: Locator
    text: str = ""
    role: str = ""
    tag: str = ""
    similarity: float = 0.0
    xpath: str = ""
    coords: Tuple[int, int] = (0, 0)

    def to_action(self) -> Dict[str, Any]:
        return {
            "element_text": self.text,
            "xpath": self.xpath,
            "coordinates": list(self.coords),
        }


class GroundingValidator:
    """
    Validates agent actions before execution.
    Uses multi-attribute cascade matching and offers auto-corrections.
    """

    def __init__(
        self,
        multi_attribute_match: bool = True,
        similarity_threshold: float = 0.85,
        reward_valid: float = 0.1,
        reward_corrected: float = -0.05,
        reward_failed: float = -0.2,
        spa_wait_ms: int = 1000,
        fingerprint_db_path: str = "./data/element_fingerprints.json",
    ):
        self.multi_attribute_match = multi_attribute_match
        self.similarity_threshold = similarity_threshold
        self.reward_valid = reward_valid
        self.reward_corrected = reward_corrected
        self.reward_failed = reward_failed
        self.spa_wait_ms = spa_wait_ms
        self._cache = GroundingCache()
        self._last_url = ""
        self._fingerprint_db = ElementFingerprintDB(fingerprint_db_path)
        self._mutation_detector = PageMutationDetector()

    async def validate(
        self,
        page: Page,
        action: str,
        params: Dict[str, Any],
    ) -> GroundingResult:
        """
        Main entry point: validate an action and optionally suggest correction.
        Returns a GroundingResult with reward and corrected action.
        Results are cached per (page_url, action_params) with automatic
        invalidation on URL changes.
        """
        current_url = page.url
        if current_url != self._last_url:
            self._cache.invalidate_url(self._last_url)
            self._last_url = current_url

        # Detect page mutations (SPA navigation, DOM changes)
        mutated = await self._mutation_detector.detect_mutation(page)
        if mutated:
            logger.debug(f"Page mutation detected on {current_url}")

        if action in ("wait", "finish"):
            return GroundingResult(
                valid=True,
                reward=0.0,
                message=f"Action '{action}' does not require grounding.",
            )

        if action == "goto":
            url = params.get("url", "")
            if not url.startswith(("http://", "https://", "about:")):
                return GroundingResult(
                    valid=False,
                    reward=self.reward_failed,
                    corrected_action=self._wait_action(),
                    message="Invalid URL format.",
                )
            return GroundingResult(
                valid=True, reward=self.reward_valid, message="URL valid."
            )

        if action == "scroll":
            return GroundingResult(
                valid=True, reward=self.reward_valid, message="Scroll is always valid."
            )

        # For click / type: check cache first
        cached = self._cache.get(current_url, params)
        if cached is not None:
            return cached

        # For click / type: need element
        locator, match_info = await robust_locate(
            page, params, multi_attribute_match=self.multi_attribute_match
        )

        if locator is not None:
            # Element found — now check interactivity
            interactivity = await self._check_interactivity(page, locator, action)
            if interactivity["ok"]:
                result = GroundingResult(
                    valid=True,
                    reward=self.reward_valid,
                    locator=locator,
                    match_info=match_info,
                    message=f"Element valid and interactive. ({match_info.get('method', 'unknown')})",
                )
                self._cache.set(current_url, params, result)
                # Record successful pattern in fingerprint DB
                self._fingerprint_db.record(
                    current_url, params, success=True, action_type=action
                )
                return result
            else:
                # Element exists but not interactive — try to find similar interactive one
                candidate = await self._find_similar_interactive(
                    page, params, expected_role=interactivity.get("expected_role", "")
                )
                if candidate and candidate.similarity >= self.similarity_threshold:
                    corrected = {
                        "action": action,
                        "params": {**params, **candidate.to_action()},
                    }
                    result = GroundingResult(
                        valid=False,
                        reward=self.reward_corrected,
                        corrected_action=corrected,
                        message=f"Original not interactive. Auto-corrected to: {candidate.text}",
                        match_info={
                            "method": "auto_corrected",
                            "similarity": candidate.similarity,
                        },
                    )
                    self._cache.set(current_url, params, result)
                    return result
                result = GroundingResult(
                    valid=False,
                    reward=self.reward_failed,
                    corrected_action=self._wait_action(),
                    message=f"Element not interactive: {interactivity.get('reason', 'unknown')}",
                )
                self._cache.set(current_url, params, result)
                return result

        # Try fingerprint DB suggestion before full failure
        suggested = self._fingerprint_db.suggest(
            current_url, action, target_text=params.get("element_text", "")
        )
        if suggested:
            logger.debug(f"Fingerprint DB suggestion: {suggested}")
            suggested_params = dict(params)
            if suggested["type"] == "id":
                suggested_params["element_id"] = suggested["value"]
            elif suggested["type"] == "text":
                suggested_params["element_text"] = suggested["value"]
            elif suggested["type"] == "xpath":
                suggested_params["xpath"] = suggested["value"]
            elif suggested["type"] == "css":
                suggested_params["css_selector"] = suggested["value"]
            locator, match_info = await robust_locate(
                page, suggested_params, multi_attribute_match=self.multi_attribute_match
            )
            if locator is not None:
                interactivity = await self._check_interactivity(page, locator, action)
                if interactivity["ok"]:
                    result = GroundingResult(
                        valid=True,
                        reward=self.reward_valid,
                        locator=locator,
                        match_info={**match_info, "method": "fingerprint_suggest"},
                        message=f"Element found via fingerprint suggestion. ({match_info.get('method', 'unknown')})",
                    )
                    self._cache.set(current_url, params, result)
                    self._fingerprint_db.record(
                        current_url, suggested_params, success=True, action_type=action
                    )
                    return result

        # Try dynamic suffix removal for CSS selectors / IDs
        if params.get("css_selector") or params.get("element_id"):
            original_sel = (
                params.get("css_selector") or f"#{params.get('element_id', '')}"
            )
            cleaned = remove_dynamic_suffix(original_sel)
            if cleaned:
                cleaned_params = dict(params)
                if params.get("css_selector"):
                    cleaned_params["css_selector"] = cleaned
                else:
                    cleaned_params["element_id"] = cleaned.lstrip("#")
                locator, match_info = await robust_locate(
                    page,
                    cleaned_params,
                    multi_attribute_match=self.multi_attribute_match,
                )
                if locator is not None:
                    interactivity = await self._check_interactivity(
                        page, locator, action
                    )
                    if interactivity["ok"]:
                        result = GroundingResult(
                            valid=True,
                            reward=self.reward_valid,
                            locator=locator,
                            match_info={
                                **match_info,
                                "method": "dynamic_suffix_removed",
                            },
                            message=f"Element found via cleaned selector: {cleaned}",
                        )
                        self._cache.set(current_url, params, result)
                        self._fingerprint_db.record(
                            current_url,
                            cleaned_params,
                            success=True,
                            action_type=action,
                        )
                        return result

        # Try structural similarity matching
        target_text = params.get("element_text", "")
        target_tag = params.get("tag", "")
        if target_text and target_tag:
            similar_loc = await find_similar_by_structure(page, target_tag, target_text)
            if similar_loc is not None:
                try:
                    count = await similar_loc.count()
                    if count > 0:
                        interactivity = await self._check_interactivity(
                            page, similar_loc, action
                        )
                        if interactivity["ok"]:
                            result = GroundingResult(
                                valid=True,
                                reward=self.reward_valid,
                                locator=similar_loc,
                                match_info={
                                    "method": "structural_similarity",
                                    "tag": target_tag,
                                    "text": target_text,
                                },
                                message=f"Element found via structural similarity matching.",
                            )
                            self._cache.set(current_url, params, result)
                            self._fingerprint_db.record(
                                current_url, params, success=True, action_type=action
                            )
                            return result
                except Exception as e:
                    logger.debug(f"Structural similarity check failed: {e}")

        # Element not found — try auto-correction via similarity
        candidate = await self._find_similar_interactive(
            page, params, expected_role="button" if action == "click" else "textbox"
        )
        if candidate and candidate.similarity >= self.similarity_threshold:
            corrected = {
                "action": action,
                "params": {**params, **candidate.to_action()},
            }
            result = GroundingResult(
                valid=False,
                reward=self.reward_corrected,
                corrected_action=corrected,
                message=f"Target not found. Auto-corrected to similar element: {candidate.text}",
                match_info={
                    "method": "similarity_match",
                    "similarity": candidate.similarity,
                },
            )
            self._cache.set(current_url, params, result)
            return result

        # Complete failure: degrade to wait
        result = GroundingResult(
            valid=False,
            reward=self.reward_failed,
            corrected_action=self._wait_action(),
            message="No matching element found. Degraded to wait.",
            match_info={"method": "none"},
        )
        self._cache.set(current_url, params, result)
        return result

    def _wait_action(self) -> Dict[str, Any]:
        """Return a safe wait action."""
        return {"action": "wait", "params": {"duration_ms": self.spa_wait_ms}}

    async def _check_interactivity(
        self, page: Page, locator: Locator, action: str
    ) -> Dict[str, Any]:
        """Check if element is visible, enabled, and role-appropriate."""
        try:
            visible = await locator.is_visible(timeout=1000)
            enabled = await locator.is_enabled(timeout=1000)
            box = await locator.bounding_box()

            if not visible:
                return {"ok": False, "reason": "not_visible"}
            if not enabled:
                return {"ok": False, "reason": "not_enabled"}
            if box is None:
                return {"ok": False, "reason": "no_bounding_box"}

            # Role check for type action
            if action == "type":
                editable = await locator.evaluate(
                    "el => el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable"
                )
                if not editable:
                    return {
                        "ok": False,
                        "reason": "not_editable",
                        "expected_role": "textbox",
                    }

            return {"ok": True}
        except Exception as e:
            logger.debug(f"Interactivity check failed: {e}")
            return {"ok": False, "reason": str(e)}

    async def _find_similar_interactive(
        self,
        page: Page,
        target_params: Dict[str, Any],
        expected_role: str = "",
    ) -> Optional[ElementCandidate]:
        """
        Find the most similar interactive element when target is not found.
        Uses text similarity (Jaccard on character bigrams) and role matching.
        """
        target_text = target_params.get("element_text", "")
        if not target_text:
            return None

        # Cache target bigrams to avoid recomputation
        target_bigrams = self._bigrams(target_text)

        interactive_selectors = [
            "button",
            "a",
            "input",
            "textarea",
            "select",
            "[role='button']",
            "[role='link']",
            "[role='textbox']",
            "[onclick]",
        ]
        candidates: List[ElementCandidate] = []

        for sel in interactive_selectors:
            try:
                locs = page.locator(sel)
                count = await locs.count()
                for i in range(min(count, 50)):  # limit for speed
                    loc = locs.nth(i)
                    try:
                        visible = await loc.is_visible(timeout=500)
                        if not visible:
                            continue
                        text = await loc.text_content() or ""
                        text = text.strip()[:100]
                        tag = await loc.evaluate("el => el.tagName.toLowerCase()")
                        bbox = await loc.bounding_box()
                        coords = (int(bbox["x"]), int(bbox["y"])) if bbox else (0, 0)

                        sim = self._text_similarity_cached(
                            target_text, text, target_bigrams
                        )
                        # Boost if role matches (exact match, not substring)
                        if expected_role and expected_role == tag:
                            sim = min(1.0, sim + 0.1)

                        candidates.append(
                            ElementCandidate(
                                locator=loc,
                                text=text,
                                role=tag,
                                tag=tag,
                                similarity=sim,
                                xpath=f"//{tag}[contains(text(), '{escape_xpath_string(text[:20])}')]",
                                coords=coords,
                            )
                        )
                    except Exception as e:
                        logger.debug(f"Candidate evaluation failed: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Selector evaluation failed ({sel}): {e}")
                continue

        if not candidates:
            return None

        candidates.sort(key=lambda c: c.similarity, reverse=True)
        best = candidates[0]
        return (
            best if best.similarity >= 0.5 else None
        )  # lower threshold for suggestion

    @staticmethod
    def _bigrams(s: str) -> set:
        """Compute character bigrams for a string."""
        s = s.lower().strip()
        return set(s[i : i + 2] for i in range(len(s) - 1))

    @classmethod
    def _text_similarity_cached(
        cls, a: str, b: str, a_bigrams: Optional[set] = None
    ) -> float:
        """Jaccard similarity on character bigrams with optional cached bigrams for `a`."""
        if not a or not b:
            return 0.0
        a = a.lower().strip()
        b = b.lower().strip()
        if a == b:
            return 1.0
        bg_a = a_bigrams if a_bigrams is not None else cls._bigrams(a)
        bg_b = cls._bigrams(b)
        inter = len(bg_a & bg_b)
        union = len(bg_a | bg_b)
        return inter / union if union > 0 else 0.0

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """Simple Jaccard similarity on character bigrams."""
        if not a or not b:
            return 0.0
        a = a.lower().strip()
        b = b.lower().strip()
        if a == b:
            return 1.0

        def bigrams(s):
            return set(s[i : i + 2] for i in range(len(s) - 1))

        bg_a = bigrams(a)
        bg_b = bigrams(b)
        inter = len(bg_a & bg_b)
        union = len(bg_a | bg_b)
        return inter / union if union > 0 else 0.0

    async def validate_and_correct(
        self, page: Page, action: str, params: Dict[str, Any]
    ) -> Tuple[bool, float, Optional[Dict[str, Any]], str]:
        """
        Convenience wrapper returning (is_valid, reward, corrected_action_dict, message).
        corrected_action_dict has keys 'action' and 'params'.
        """
        result = await self.validate(page, action, params)
        return (
            result.valid,
            result.reward,
            result.corrected_action,
            result.message,
        )
