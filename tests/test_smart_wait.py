"""Unit tests for smart wait."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from step_rl.environment.smart_wait import smart_wait


class TestSmartWait:
    @pytest.fixture
    def mock_page(self):
        page = MagicMock()
        locator = MagicMock()
        locator.wait_for = AsyncMock()
        page.locator = MagicMock(return_value=locator)
        page.evaluate = AsyncMock(return_value="stable")
        return page

    @pytest.mark.asyncio
    async def test_element_already_visible(self, mock_page):
        success, elapsed = await smart_wait(
            mock_page, {"element_id": "test"}, max_wait_ms=1000
        )
        assert success is True

    @pytest.mark.asyncio
    async def test_element_not_found(self, mock_page):
        mock_page.locator.return_value.wait_for = AsyncMock(
            side_effect=Exception("Timeout")
        )
        success, elapsed = await smart_wait(
            mock_page, {"element_id": "missing"}, max_wait_ms=100
        )
        assert success is True  # SPA detection fallback returns True

    @pytest.mark.asyncio
    async def test_spa_detection_false(self, mock_page):
        mock_page.evaluate = AsyncMock(return_value=None)
        success, elapsed = await smart_wait(mock_page, {}, max_wait_ms=100)
        assert success is False

    @pytest.mark.asyncio
    async def test_no_element_id(self, mock_page):
        success, elapsed = await smart_wait(mock_page, {}, max_wait_ms=1000)
        assert success is True
