"""Sub-goal completion reward for better credit assignment."""

from typing import Any, List


def compute_subgoal_reward(
    task: Any,
    action_history: List[str],
    current_subgoal_idx: int,
    previous_subgoal_idx: int,
    progress_delta: float,
) -> float:
    """Reward sub-goal completion rather than raw progress delta.

    Args:
        task: The current task object.
        action_history: List of actions taken so far.
        current_subgoal_idx: Current predicted subgoal index.
        previous_subgoal_idx: Subgoal index from previous step.
        progress_delta: Change in progress estimate since last step.

    Returns:
        Scalar reward signal.
    """
    if current_subgoal_idx > previous_subgoal_idx:
        return 0.3  # 子目标完成奖励
    elif progress_delta > 0.01:
        return progress_delta * 0.1
    elif progress_delta < -0.1:
        return -0.05  # 轻微倒退惩罚
    return 0.0
