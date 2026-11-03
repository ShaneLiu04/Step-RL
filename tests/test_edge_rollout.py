"""Pure numerical helpers used by Step-GRPO (no browser)."""

from __future__ import annotations

from step_rl.edge.rollout import (
    Rollout,
    StepRecord,
    assign_group_advantages,
    returns_to_go,
    step_reward,
)


def _step(reward: float) -> StepRecord:
    return StepRecord(
        prompt="p",
        prompt_ids=[1],
        response_ids=[2],
        old_logprobs=[0.0],
        response_text="{}",
        action={"action": "wait", "params": {}},
        exec_ok=True,
        error="",
        phi_before=0.0,
        phi_after=0.0,
        reward=reward,
    )


def test_returns_to_go_discounting():
    assert returns_to_go([1.0, 0.0], gamma=0.5) == [1.0, 0.0]
    assert returns_to_go([0.0, 1.0], gamma=0.5) == [0.5, 1.0]


def test_group_advantage_is_normalized_per_task():
    a = Rollout("t1", True, 1.0, [_step(1.0), _step(1.0)])
    b = Rollout("t1", False, 0.0, [_step(0.0), _step(0.0)])
    c = Rollout("t2", True, 1.0, [_step(2.0), _step(2.0)])
    d = Rollout("t2", False, 0.0, [_step(0.0), _step(0.0)])
    assign_group_advantages([a, b, c, d])
    assert a.steps[0].advantage > 0 > b.steps[0].advantage
    assert c.steps[0].advantage > 0 > d.steps[0].advantage


def test_vgdp_rewards_progress():
    gain = step_reward(0.0, 0.5, True, False, False, mode="vgdp")
    none = step_reward(0.0, 0.0, True, False, False, mode="vgdp")
    sparse_gain = step_reward(0.0, 0.5, True, False, False, mode="sparse")
    assert gain > none
    assert sparse_gain == -0.02
