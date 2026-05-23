"""Tests for shared locator module."""

import pytest

pytest.importorskip("playwright")

from step_rl.environment.grounding_validator import GroundingValidator
from step_rl.environment.locator import robust_locate


class TestBigrams:
    def test_basic(self):
        bg = GroundingValidator._bigrams("hello")
        assert "he" in bg
        assert "el" in bg
        assert "ll" in bg
        assert "lo" in bg

    def test_short(self):
        assert GroundingValidator._bigrams("a") == set()
        assert GroundingValidator._bigrams("") == set()


class TestRobustLocateMock:
    """Mock-based tests for robust_locate logic."""

    @pytest.fixture
    def mock_page(self):
        class FakeLocator:
            def __init__(self, found=True):
                self._found = found

            async def count(self):
                return 1 if self._found else 0

            @property
            def first(self):
                return self

        class FakePage:
            def __init__(self):
                self._selectors = {}

            def set_selector(self, sel, found=True):
                self._selectors[sel] = found

            def locator(self, sel):
                return FakeLocator(self._selectors.get(sel, False))

        return FakePage()

    @pytest.mark.asyncio
    async def test_find_by_id(self, mock_page):
        mock_page.set_selector("#my-id", True)
        loc, info = await robust_locate(mock_page, {"element_id": "my-id"})
        assert loc is not None
        assert info["method"] == "id_hash"

    @pytest.mark.asyncio
    async def test_find_by_text(self, mock_page):
        mock_page.set_selector("text=Submit", True)
        loc, info = await robust_locate(mock_page, {"element_text": "Submit"})
        assert loc is not None
        assert info["method"] == "text_exact"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_page):
        loc, info = await robust_locate(mock_page, {"element_text": "Missing"})
        assert loc is None
        assert info["method"] == "none"
