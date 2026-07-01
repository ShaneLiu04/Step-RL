"""WandB + MLflow monitoring integration."""
import os
from typing import Dict, Any, Optional
from pathlib import Path


class TrainingMonitor:
    """Unified training monitor supporting WandB and MLflow backends.

    Args:
        project: WandB project name.
        experiment: Experiment / run name.
        use_wandb: Whether to enable WandB logging.
        use_mlflow: Whether to enable MLflow logging.
    """

    def __init__(
        self,
        project: str = "step-rl",
        experiment: str = "default",
        use_wandb: bool = True,
        use_mlflow: bool = False,
    ):
        self.project = project
        self.experiment = experiment
        self.use_wandb = use_wandb
        self.use_mlflow = use_mlflow
        self._run = None
        self._mlflow_active = False

        if use_wandb:
            try:
                import wandb

                self._run = wandb.init(
                    project=project, name=experiment, config={}
                )
            except ImportError:
                pass

        if use_mlflow:
            try:
                import mlflow

                mlflow.set_experiment(experiment)
                mlflow.start_run()
                self._mlflow_active = True
            except ImportError:
                pass

    def log(self, metrics: Dict[str, Any], step: Optional[int] = None):
        """Log scalar metrics to all active backends."""
        if self._run is not None:
            self._run.log(metrics, step=step)
        if self._mlflow_active:
            try:
                import mlflow

                for key, value in metrics.items():
                    if isinstance(value, (int, float)):
                        mlflow.log_metric(key, value, step=step)
            except ImportError:
                pass

    def log_config(self, config: Dict[str, Any]):
        """Log configuration dict to all active backends."""
        if self._run is not None:
            import wandb

            wandb.config.update(config)
        if self._mlflow_active:
            try:
                import mlflow

                for key, value in config.items():
                    mlflow.log_param(key, value)
            except ImportError:
                pass

    def log_episode(self, episode_data: Dict[str, Any]):
        """Log standardized episode metrics."""
        metrics = {
            "episode/return": episode_data.get("total_return", 0),
            "episode/length": episode_data.get("length", 0),
            "episode/success": episode_data.get("success", False),
            "episode/grounding_accuracy": episode_data.get(
                "grounding_accuracy", 1.0
            ),
            "episode/loop_rate": episode_data.get("loop_rate", 0),
        }
        self.log(metrics, step=episode_data.get("step"))

    def finish(self):
        """Finalize all active backends."""
        if self._run is not None:
            self._run.finish()
        if self._mlflow_active:
            try:
                import mlflow

                mlflow.end_run()
            except ImportError:
                pass
