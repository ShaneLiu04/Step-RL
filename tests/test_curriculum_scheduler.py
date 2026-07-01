"""
Unit tests for CurriculumScheduler.
Tests: task sampling, reward weight scheduling, promotion logic.
"""

import unittest

from step_rl.training.curriculum_scheduler import (
    BanditTaskSelector,
    CurriculumScheduler,
    Task,
)


class TestCurriculumScheduler(unittest.TestCase):
    def setUp(self):
        self.scheduler = CurriculumScheduler(
            total_epochs=100,
            promotion_threshold=0.90,
            seed=42,
        )
        tasks = [
            Task("t1", "搜索商品", 1),
            Task("t2", "加入购物车", 1),
            Task("t3", "填写地址", 2),
            Task("t4", "提交订单", 2),
            Task("t5", "使用优惠券", 3),
            Task("t6", "跨店结算", 4),
        ]
        self.scheduler.register_tasks(tasks)

    def test_initial_level(self):
        self.assertEqual(self.scheduler.current_level, 1)

    def test_sample_task_early_epoch(self):
        task = self.scheduler.sample_task(epoch=0)
        self.assertIsNotNone(task)
        self.assertIn(task.level, [1, 2])  # early epochs favor low levels

    def test_reward_weights_early(self):
        weights = self.scheduler.get_reward_weights(epoch=10)
        self.assertEqual(weights["beta"], 2.0)  # grounding dominant early
        self.assertEqual(weights["alpha"], 1.0)

    def test_reward_weights_mid(self):
        weights = self.scheduler.get_reward_weights(epoch=50)
        self.assertEqual(weights["alpha"], 2.0)  # progress dominant mid
        self.assertEqual(weights["beta"], 1.0)

    def test_reward_weights_late(self):
        weights = self.scheduler.get_reward_weights(epoch=80)
        self.assertEqual(weights["alpha"], 2.5)  # progress dominant late
        self.assertEqual(weights["epsilon"], 0.2)  # novelty decayed

    def test_promotion(self):
        # Simulate high success rate on level 1
        for _ in range(15):
            self.scheduler.record_episode_result(1, success=True)
        self.assertEqual(self.scheduler.current_level, 2)

    def test_no_promotion_with_low_success(self):
        for _ in range(5):
            self.scheduler.record_episode_result(1, success=False)
        self.assertEqual(self.scheduler.current_level, 1)

    def test_stats(self):
        self.scheduler.record_episode_result(1, success=True)
        stats = self.scheduler.get_stats()
        self.assertIn("level_1_success", stats)


class TestBanditTaskSelector(unittest.TestCase):
    def setUp(self):
        self.selector = BanditTaskSelector(num_arms=4, seed=42)

    def test_initial_select(self):
        arm = self.selector.select()
        self.assertEqual(arm, 0)  # first un-pulled arm

    def test_exploration_all_arms(self):
        arms = []
        for _ in range(4):
            arm = self.selector.select()
            arms.append(arm)
            self.selector.update(arm, 1.0)
        self.assertEqual(len(set(arms)), 4)  # all arms explored

    def test_ucb_exploitation(self):
        # Update arm 0 with high reward, arm 1 with low reward
        self.selector.select()
        self.selector.update(0, 1.0)
        self.selector.select()
        self.selector.update(1, 0.0)
        # After many pulls, should favor arm 0
        for _ in range(20):
            arm = self.selector.select()
            self.selector.update(arm, 1.0 if arm == 0 else 0.0)
        self.assertEqual(self.selector.values[0], 1.0)

    def test_ucb_exploration(self):
        # Update arm 0 with high reward, leave arm 2 un-pulled
        for _ in range(10):
            self.selector.select()
            self.selector.update(0, 1.0)
        # After some time, UCB should explore an un-pulled arm first
        arm = self.selector.select()
        self.assertIn(arm, [1, 2, 3])  # un-pulled arms get priority

    def test_stats(self):
        self.selector.select()
        self.selector.update(0, 1.0)
        stats = self.selector.get_stats()
        self.assertEqual(stats["total_pulls"], 1)
        self.assertEqual(stats["counts"], [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(stats["values"], [1.0, 0.0, 0.0, 0.0])

    def test_update_decreases_value(self):
        self.selector.select()
        self.selector.update(0, 1.0)
        self.selector.select()
        self.selector.update(0, 0.0)
        self.assertEqual(self.selector.values[0], 0.5)

    def test_multiple_updates(self):
        for _ in range(10):
            arm = self.selector.select()
            self.selector.update(arm, 0.5)
        self.assertEqual(self.selector.total_pulls, 10)


if __name__ == "__main__":
    unittest.main()
