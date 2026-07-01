"""Unit tests for trl adapter wrappers."""

import pytest

from step_rl.training.gae_utils import adaptive_gae_lambda
from step_rl.training.kl_controller import AdaptiveKLController


class TestAdaptiveKLController:
    def test_initial_value(self):
        ctrl = AdaptiveKLController(init_kl_coef=0.1, target_kl=0.1)
        assert ctrl.get_coef() == 0.1

    def test_adaptation_high_kl(self):
        ctrl = AdaptiveKLController(init_kl_coef=0.1, target_kl=0.1)
        for _ in range(100):
            ctrl.update(0.2)  # high KL
        assert ctrl.get_coef() > 0.1

    def test_adaptation_low_kl(self):
        ctrl = AdaptiveKLController(init_kl_coef=0.1, target_kl=0.1)
        for _ in range(100):
            ctrl.update(0.01)  # low KL
        assert ctrl.get_coef() < 0.1

    def test_clipping(self):
        ctrl = AdaptiveKLController(init_kl_coef=0.1)
        for _ in range(1000):
            ctrl.update(10.0)
        assert ctrl.get_coef() <= 0.5

    def test_min_clipping(self):
        ctrl = AdaptiveKLController(init_kl_coef=0.1, target_kl=0.1)
        for _ in range(1000):
            ctrl.update(0.001)  # very low KL
        assert ctrl.get_coef() >= 0.01

    def test_target_kl_custom(self):
        ctrl = AdaptiveKLController(init_kl_coef=0.2, target_kl=0.05)
        for _ in range(50):
            ctrl.update(0.1)  # above target
        assert ctrl.get_coef() > 0.2


class TestAdaptiveGAE:
    def test_early_epoch(self):
        lam = adaptive_gae_lambda(0, 100, avg_episode_length=10)
        assert 0.80 <= lam <= 0.90

    def test_late_epoch(self):
        lam = adaptive_gae_lambda(90, 100, avg_episode_length=10)
        assert 0.95 <= lam <= 0.99

    def test_long_episode_adjustment(self):
        lam_short = adaptive_gae_lambda(50, 100, avg_episode_length=5)
        lam_long = adaptive_gae_lambda(50, 100, avg_episode_length=20)
        assert lam_long > lam_short

    def test_monotonic_increase(self):
        lam_0 = adaptive_gae_lambda(0, 100)
        lam_50 = adaptive_gae_lambda(50, 100)
        lam_99 = adaptive_gae_lambda(99, 100)
        assert lam_0 <= lam_50 <= lam_99

    def test_clip_upper_bound(self):
        lam = adaptive_gae_lambda(999, 1000, avg_episode_length=100)
        assert lam <= 0.99

    def test_clip_lower_bound(self):
        lam = adaptive_gae_lambda(-10, 100)
        assert lam >= 0.80
