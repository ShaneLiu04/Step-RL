"""GAE utilities for RL training."""

import numpy as np


def adaptive_gae_lambda(epoch, total_epochs, avg_episode_length=10):
    """Return adaptive GAE lambda based on training progress and episode length.
    
    Early epochs: lower lambda for higher bias (more stable)
    Late epochs: higher lambda for lower bias (more accurate)
    Longer episodes: higher lambda to capture longer-term dependencies.
    
    Args:
        epoch: Current epoch (0-indexed)
        total_epochs: Total number of epochs
        avg_episode_length: Average episode length
        
    Returns:
        GAE lambda value in [0.8, 0.99]
    """
    progress = epoch / max(1, total_epochs)
    
    # Base lambda: interpolate from 0.85 to 0.97
    base = 0.85 + 0.12 * progress
    
    # Adjust for episode length: longer episodes benefit from higher lambda
    if avg_episode_length > 10:
        base += 0.02 * (avg_episode_length / 10)
    
    return float(np.clip(base, 0.80, 0.99))
