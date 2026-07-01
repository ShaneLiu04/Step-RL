"""Prioritized Experience Replay Buffer with SumTree for Step-RL v3.0."""

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class Trajectory:
    """A single episode trajectory.

    Stores the full sequence of observations, actions, rewards, and auxiliary
    information produced during one environment rollout.
    """

    observations: List[str] = field(default_factory=list)
    responses: List[str] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    rewards: List[float] = field(default_factory=list)
    values: List[float] = field(default_factory=list)
    log_probs: List[float] = field(default_factory=list)
    dones: List[bool] = field(default_factory=list)
    infos: List[Dict[str, Any]] = field(default_factory=list)
    total_return: float = 0.0
    length: int = 0
    success: bool = False


class SumTree:
    """Binary SumTree for O(log n) priority sampling.

    The tree is stored as a flat array where leaf nodes (indices
    ``capacity - 1`` to ``2 * capacity - 2``) hold the individual priorities
    and internal nodes hold the sum of their children. This allows both
    priority updates and proportional sampling in logarithmic time.
    """

    def __init__(self, capacity: int) -> None:
        """Initialize the SumTree with the given capacity.

        Args:
            capacity: Maximum number of leaf nodes (experiences) the tree can
                hold. Must be a positive integer.
        """
        self.capacity: int = capacity
        self.tree: np.ndarray = np.zeros(2 * capacity - 1, dtype=np.float64)
        self.data: List[Optional[Any]] = [None] * capacity
        self.write: int = 0
        self.n_entries: int = 0

    def _propagate(self, idx: int, change: float) -> None:
        """Propagate a priority change up the tree.

        Args:
            idx: Tree index where the change originated.
            change: Delta to add to every parent node on the path to the root.
        """
        parent: int = (idx - 1) // 2
        self.tree[parent] += change
        if parent != 0:
            self._propagate(parent, change)

    def _retrieve(self, idx: int, s: float) -> int:
        """Recursively find the leaf index corresponding to cumulative priority *s*.

        Args:
            idx: Current tree index (starting from the root).
            s: Cumulative priority value to locate.

        Returns:
            The leaf tree index that straddles *s*.
        """
        left: int = 2 * idx + 1
        right: int = left + 1
        if left >= len(self.tree):
            return idx
        if s <= self.tree[left]:
            return self._retrieve(left, s)
        return self._retrieve(right, s - self.tree[left])

    def total(self) -> float:
        """Return the total priority sum stored in the tree."""
        return self.tree[0]

    def add(self, priority: float, data: Any) -> int:
        """Add *data* with the given *priority* to the tree.

        Args:
            priority: Non-negative priority value for the new item.
            data: Arbitrary data payload (typically a ``Trajectory``).

        Returns:
            The write pointer (data index) after insertion.
        """
        tree_idx: int = self.write + self.capacity - 1
        self.data[self.write] = data
        self._update(tree_idx, priority)
        self.write = (self.write + 1) % self.capacity
        self.n_entries = min(self.n_entries + 1, self.capacity)
        return self.write

    def _update(self, idx: int, priority: float) -> None:
        """Update the priority at *idx* and propagate the delta upward.

        Args:
            idx: Tree index to update.
            priority: New priority value.
        """
        change: float = priority - self.tree[idx]
        self.tree[idx] = priority
        self._propagate(idx, change)

    def get(self, s: float) -> Tuple[int, float, Any]:
        """Retrieve the data item whose cumulative priority interval contains *s*.

        Args:
            s: A uniform random sample from ``[0, total_priority)``.

        Returns:
            A tuple of ``(data_index, priority, data)``.
        """
        idx: int = self._retrieve(0, s)
        data_idx: int = idx - self.capacity + 1
        return data_idx, self.tree[idx], self.data[data_idx]

    def update_priority(self, data_idx: int, priority: float) -> None:
        """Update the priority for the item stored at *data_idx*.

        Args:
            data_idx: Flat buffer index (0-based).
            priority: New priority value.
        """
        tree_idx: int = data_idx + self.capacity - 1
        self._update(tree_idx, priority)


class PrioritizedReplayBuffer:
    """Trajectory-level Prioritized Experience Replay (PER) buffer.

    Uses a :class:`SumTree` for proportional sampling and importance-sampling
    (IS) weight computation.  Priorities are raised to the power ``alpha``;
    IS weights are raised to ``-beta`` and normalized by the maximum weight in
    the batch.  ``beta`` is annealed toward ``beta_max`` after every sample.

    Attributes:
        tree: Underlying SumTree instance.
        alpha: Priority exponent (0 = uniform, 1 = fully prioritized).
        beta: Current IS exponent.
        beta_increment: Per-sample annealing step for ``beta``.
        beta_max: Upper bound for ``beta``.
        epsilon: Small constant to avoid zero priorities.
    """

    def __init__(
        self,
        capacity: int = 10000,
        alpha: float = 0.6,
        beta: float = 0.4,
        beta_increment: float = 0.001,
    ) -> None:
        """Initialize the PER buffer.

        Args:
            capacity: Maximum number of trajectories to store.
            alpha: Priority exponent for prioritization strength.
            beta: Initial IS exponent for bias correction.
            beta_increment: Annealing step applied after each ``sample()`` call.
        """
        self.tree: SumTree = SumTree(capacity)
        self.alpha: float = alpha
        self.beta: float = beta
        self.beta_increment: float = beta_increment
        self.beta_max: float = 1.0
        self.epsilon: float = 1e-6
        self._max_priority: float = 1.0

    def add(self, trajectory: Trajectory, priority: Optional[float] = None) -> None:
        """Store a trajectory with an optional initial priority.

        If *priority* is ``None``, the buffer reuses the highest priority seen
        so far, encouraging exploration of recently added experiences.

        Args:
            trajectory: Episode trajectory to store.
            priority: Raw priority value (e.g. absolute TD-error or return).
                If ``None``, ``self._max_priority`` is used.
        """
        p: float = priority if priority is not None else self._max_priority
        p = (abs(p) + self.epsilon) ** self.alpha
        self.tree.add(p, trajectory)

    def sample(
        self, batch_size: int
    ) -> Tuple[List[Trajectory], np.ndarray, np.ndarray]:
        """Sample a batch of trajectories with importance-sampling weights.

        The sampling strategy divides the total priority range into
        ``batch_size`` equal segments and draws one uniform sample from each
        segment.  This guarantees a diverse batch while respecting the
        priority distribution.

        Args:
            batch_size: Number of trajectories to sample.

        Returns:
            A tuple of ``(trajectories, data_indices, importance_weights)``.
            ``importance_weights`` is a 1-D array normalized so that the maximum
            weight in the batch equals ``1.0``.
        """
        trajectories: List[Trajectory] = []
        indices: List[int] = []
        priorities: List[float] = []

        segment: float = self.tree.total() / batch_size

        for i in range(batch_size):
            a: float = segment * i
            b: float = segment * (i + 1)
            s: float = random.uniform(a, b)
            data_idx, priority, traj = self.tree.get(s)
            indices.append(data_idx)
            priorities.append(priority)
            trajectories.append(traj)

        # Compute importance-sampling weights
        probs: np.ndarray = np.array(priorities, dtype=np.float64) / self.tree.total()
        n_entries: int = self.tree.n_entries
        weights: np.ndarray = (n_entries * probs) ** (-self.beta)
        weights /= weights.max()

        # Anneal beta toward beta_max
        self.beta = min(self.beta_max, self.beta + self.beta_increment)

        return trajectories, np.array(indices), weights

    def update_priorities(self, indices: np.ndarray, priorities: np.ndarray) -> None:
        """Update stored priorities after a training step.

        Args:
            indices: Data indices (as returned by :meth:`sample`) whose
                priorities should be updated.
            priorities: New raw priority values (e.g. updated TD-errors).
        """
        for idx, p in zip(indices, priorities):
            self._max_priority = max(self._max_priority, abs(p))
            self.tree.update_priority(idx, (abs(p) + self.epsilon) ** self.alpha)

    def __len__(self) -> int:
        """Return the current number of stored trajectories."""
        return self.tree.n_entries
