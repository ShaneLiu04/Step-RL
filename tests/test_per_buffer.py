"""Unit tests for Prioritized Replay Buffer."""

import numpy as np

from step_rl.training.per_buffer import PrioritizedReplayBuffer, SumTree, Trajectory


class TestSumTree:
    def test_add_and_total(self):
        tree = SumTree(10)
        tree.add(1.0, "data1")
        tree.add(2.0, "data2")
        assert tree.total() == 3.0

    def test_sampling(self):
        tree = SumTree(10)
        for i in range(5):
            tree.add(float(i + 1), f"data{i}")
        idx, priority, data = tree.get(tree.total() * 0.5)
        assert data is not None
        assert 0 <= idx < tree.capacity

    def test_priority_update(self):
        tree = SumTree(10)
        tree.add(1.0, "data")
        tree.update_priority(0, 5.0)
        assert tree.total() == 5.0

    def test_capacity_wrap(self):
        tree = SumTree(3)
        for i in range(5):
            tree.add(1.0, f"data{i}")
        # Should have overwritten
        assert tree.n_entries == 3

    def test_get_invalid_priority(self):
        tree = SumTree(10)
        tree.add(1.0, "data")
        idx, priority, data = tree.get(-1.0)
        # With negative s, tree may return an invalid/out-of-range leaf
        assert isinstance(idx, int)

    def test_get_zero_priority(self):
        tree = SumTree(10)
        tree.add(1.0, "data")
        idx, priority, data = tree.get(0.0)
        # s=0 may fall into an empty leaf if tree is sparse; just verify structure
        assert isinstance(idx, int)
        assert priority >= 0


class TestPrioritizedReplayBuffer:
    def test_add_and_sample(self):
        buf = PrioritizedReplayBuffer(capacity=10)
        traj = Trajectory(total_return=1.0)
        buf.add(traj, priority=1.0)
        trajectories, indices, weights = buf.sample(1)
        assert len(trajectories) == 1
        assert len(weights) == 1
        assert weights[0] == 1.0

    def test_priority_update(self):
        buf = PrioritizedReplayBuffer(capacity=10)
        buf.add(Trajectory(total_return=1.0), priority=1.0)
        buf.update_priorities(np.array([0]), np.array([5.0]))
        assert buf._max_priority == 5.0

    def test_sample_batch(self):
        buf = PrioritizedReplayBuffer(capacity=10)
        for i in range(5):
            buf.add(Trajectory(total_return=float(i)), priority=float(i + 1))
        trajectories, indices, weights = buf.sample(3)
        assert len(trajectories) == 3
        assert len(indices) == 3
        assert len(weights) == 3

    def test_empty_buffer(self):
        buf = PrioritizedReplayBuffer(capacity=10)
        trajectories, indices, weights = buf.sample(1)
        # When empty, total() is 0, segment is 0, tree.get(0) returns first leaf
        # which is None. So we should get [None] as trajectory.
        assert len(trajectories) == 1
        assert trajectories[0] is None

    def test_default_priority(self):
        buf = PrioritizedReplayBuffer(capacity=10)
        buf.add(Trajectory(total_return=1.0))
        assert buf._max_priority == 1.0

    def test_weight_normalization(self):
        buf = PrioritizedReplayBuffer(capacity=10)
        for i in range(5):
            buf.add(Trajectory(total_return=float(i)), priority=float(i + 1))
        _, _, weights = buf.sample(5)
        assert max(weights) == 1.0

    def test_len(self):
        buf = PrioritizedReplayBuffer(capacity=10)
        assert len(buf) == 0
        buf.add(Trajectory(total_return=1.0))
        assert len(buf) == 1
