"""
Unit tests for StateMemory module.
Tests: hashing, loop detection, novelty bonus, reset.
"""

import unittest

import pytest

pytest.importorskip("imagehash")

from step_rl.memory.state_memory import StateMemory


class TestStateMemory(unittest.TestCase):
    def setUp(self):
        self.memory = StateMemory(
            hash_method="simple",
            max_states=100,
            loop_window=3,
            loop_penalty_base=-0.1,
            novelty_bonus_base=0.05,
        )

    def test_compute_hash_consistency(self):
        h1 = self.memory.compute_hash("<div>test</div>", "https://example.com")
        h2 = self.memory.compute_hash("<div>test</div>", "https://example.com")
        self.assertEqual(h1, h2)

    def test_compute_hash_different(self):
        h1 = self.memory.compute_hash("<div>test1</div>", "https://example.com")
        h2 = self.memory.compute_hash("<div>test2</div>", "https://example.com")
        self.assertNotEqual(h1, h2)

    def test_novelty_first_visit(self):
        h = self.memory.compute_hash("page1", "url1")
        r_loop, r_novelty, info = self.memory.update(h)
        self.assertTrue(info["is_novel"])
        self.assertGreater(r_novelty, 0)
        self.assertEqual(r_loop, 0)

    def test_novelty_second_visit(self):
        h = self.memory.compute_hash("page1", "url1")
        self.memory.update(h)
        r_loop, r_novelty, info = self.memory.update(h)
        self.assertFalse(info["is_novel"])
        self.assertEqual(r_novelty, 0)

    def test_loop_detection(self):
        h = self.memory.compute_hash("page1", "url1")
        # Visit multiple different states first
        for i in range(5):
            self.memory.update(self.memory.compute_hash(f"page{i}", f"url{i}"))
        # Create a loop by revisiting within window
        self.memory.update(h)
        self.memory.update(self.memory.compute_hash("other", "other"))
        self.memory.update(h)
        r_loop, r_novelty, info = self.memory.update(h)
        self.assertLess(r_loop, 0)
        self.assertGreater(info["loop_count"], 0)

    def test_reset_clears_history(self):
        h = self.memory.compute_hash("page1", "url1")
        self.memory.update(h)
        self.memory.reset()
        r_loop, r_novelty, info = self.memory.update(h)
        # After reset, history is cleared but visited set remains
        self.assertEqual(r_loop, 0)
        self.assertFalse(info["is_novel"])  # still in visited set

    def test_full_reset(self):
        h = self.memory.compute_hash("page1", "url1")
        self.memory.update(h)
        self.memory.full_reset()
        r_loop, r_novelty, info = self.memory.update(h)
        self.assertTrue(info["is_novel"])
        self.assertEqual(self.memory.visited_count, 1)

    def test_minhash_deterministic(self):
        """Test minhash method produces same hash for same input."""
        mem = StateMemory(hash_method="minhash")
        h1 = mem.compute_hash("hello world test page", "https://example.com")
        h2 = mem.compute_hash("hello world test page", "https://example.com")
        self.assertEqual(h1, h2)

    def test_minhash_different_content(self):
        """Test minhash produces different hashes for different content."""
        mem = StateMemory(hash_method="minhash")
        h1 = mem.compute_hash("hello world test page", "https://example.com")
        h2 = mem.compute_hash("goodbye world test page", "https://example.com")
        self.assertNotEqual(h1, h2)

    def test_deterministic_repeat(self):
        """Test same input always returns same hash (deterministic)."""
        mem = StateMemory(hash_method="simple")
        h1 = mem.compute_hash("test content for hashing", "https://example.com")
        h2 = mem.compute_hash("test content for hashing", "https://example.com")
        self.assertEqual(h1, h2)

    def test_lru_eviction(self):
        """Test LRU eviction when max_states exceeded."""
        mem = StateMemory(max_states=3)
        for i in range(5):
            mem.update(f"state_{i}")
        self.assertEqual(len(mem._visited_hashes), 3)

    def test_visit_count_increment(self):
        """Test visit count increments correctly."""
        h = self.memory.compute_hash("page1", "url1")
        self.memory.update(h)
        self.memory.update(h)
        info = self.memory.update(h)[2]
        self.assertEqual(info["visit_count"], 3)

    def test_loop_penalty_scales(self):
        """Test loop penalty scales with repeated visits."""
        h = self.memory.compute_hash("page1", "url1")
        penalties = []
        for _ in range(5):
            self.memory.reset()
            for _ in range(3):
                self.memory.update(h)
            r_loop, _, _ = self.memory.update(h)
            penalties.append(r_loop)
        self.assertLessEqual(
            penalties[-1], penalties[0]
        )  # penalty stays same or gets more negative

    def test_novelty_decay(self):
        """Test novelty bonus decreases as more states are visited."""
        mem = StateMemory(max_states=10, novelty_bonus_base=0.05)
        bonuses = []
        for i in range(10):
            h = mem.compute_hash(f"page{i}", f"url{i}")
            _, bonus, _ = mem.update(h)
            bonuses.append(bonus)
        self.assertGreater(bonuses[0], bonuses[-1])  # first bonus > last bonus


if __name__ == "__main__":
    unittest.main()
