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


if __name__ == "__main__":
    unittest.main()
