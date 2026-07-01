"""Adaptive KL Controller for RL training."""


class AdaptiveKLController:
    """Adaptive KL divergence coefficient controller.

    Adjusts KL coefficient based on observed KL divergence to keep it near target.
    """

    def __init__(self, init_kl_coef=0.1, target_kl=0.1, min_coef=0.01, max_coef=0.5):
        self.kl_coef = init_kl_coef
        self.target_kl = target_kl
        self.min_coef = min_coef
        self.max_coef = max_coef

    def get_coef(self):
        """Return current KL coefficient."""
        return self.kl_coef

    def update(self, kl_value):
        """Update KL coefficient based on observed KL divergence."""
        if kl_value > self.target_kl:
            # Increase penalty if KL is too high
            self.kl_coef *= 1.1
        else:
            # Decrease penalty if KL is too low
            self.kl_coef *= 0.9
        # Clip to valid range
        self.kl_coef = max(self.min_coef, min(self.max_coef, self.kl_coef))
