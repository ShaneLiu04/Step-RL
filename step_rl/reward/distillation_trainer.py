"""Distillation trainer for Progress Estimator (8B teacher -> 1.5B student)."""

from pathlib import Path
from typing import Any, Dict, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from step_rl.reward.progress_estimator import ProgressEstimator, ProgressOutput
from step_rl.utils.logging_utils import get_logger

logger = get_logger(__name__)


class DistillationTrainer:
    """Train a smaller student model to mimic the teacher's progress predictions."""

    def __init__(
        self,
        teacher: ProgressEstimator,
        student_encoder_name: str = "Qwen/Qwen2.5-1.5B-Instruct",
        device: torch.device = None,
        temperature: float = 2.0,
    ):
        self.device = device or torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        self.teacher = teacher.to(self.device)
        self.teacher.eval()
        for param in self.teacher.parameters():
            param.requires_grad = False

        # Create student model with same architecture but smaller encoder
        teacher_hidden = getattr(teacher, "hidden_dim", 512)
        teacher_layers = getattr(teacher, "num_layers", 3)
        student_hidden = max(teacher_hidden // 2, 128)
        student_layers = max(teacher_layers - 1, 2)

        self.student = ProgressEstimator(
            encoder_name=student_encoder_name,
            hidden_dim=student_hidden,
            num_layers=student_layers,
            use_uncertainty=teacher.use_uncertainty,
            uncertainty_method=teacher.uncertainty_method,
            freeze_encoder=False,  # Train student encoder
            device_map="auto" if torch.cuda.is_available() else "cpu",
        ).to(self.device)

        self.temperature = temperature
        self.optimizer = torch.optim.AdamW(
            self.student.parameters(), lr=2e-5, weight_decay=0.01
        )

    def distillation_loss(
        self, teacher_out: ProgressOutput, student_out: ProgressOutput
    ) -> torch.Tensor:
        """Compute distillation loss."""
        # MSE on progress
        mse = F.mse_loss(student_out.progress, teacher_out.progress)

        # KL divergence on uncertainty distribution (if available)
        kl = 0.0
        if (
            teacher_out.uncertainty is not None
            and student_out.uncertainty is not None
            and isinstance(teacher_out.uncertainty, torch.Tensor)
            and isinstance(student_out.uncertainty, torch.Tensor)
        ):
            # Ensure tensors have same shape for KL computation
            t_unc = teacher_out.uncertainty
            s_unc = student_out.uncertainty
            if t_unc.dim() == 1 and s_unc.dim() == 1:
                # Add dummy dimension for softmax over a single value if needed,
                # or treat as scalar MSE if single value. For KL we need distributions.
                # If uncertainty is a scalar per sample, we can just use MSE for it.
                kl = F.mse_loss(s_unc, t_unc) * 0.5
            else:
                teacher_soft = F.softmax(t_unc / self.temperature, dim=-1)
                student_log_soft = F.log_softmax(s_unc / self.temperature, dim=-1)
                kl = F.kl_div(student_log_soft, teacher_soft, reduction="batchmean") * (
                    self.temperature**2
                )

        # Subgoal alignment (if available)
        subgoal_loss = 0.0
        if teacher_out.subgoals is not None and student_out.subgoals is not None:
            subgoal_loss = F.mse_loss(student_out.subgoals, teacher_out.subgoals)

        return mse + 0.5 * kl + 0.3 * subgoal_loss

    def train_step(self, batch: Dict[str, torch.Tensor]) -> float:
        """Single distillation step."""
        self.student.train()
        self.optimizer.zero_grad()

        text_batch = batch.get("text")
        goal_batch = batch.get("goal")
        step_count = batch.get("step_count", 0)
        vision_embedding = batch.get("vision_embedding")

        # Teacher prediction (no grad)
        with torch.no_grad():
            if text_batch is not None and isinstance(text_batch, list):
                teacher_out = self.teacher.forward_text(
                    observation_text=(
                        text_batch[0] if len(text_batch) == 1 else text_batch
                    ),
                    goal=goal_batch[0] if isinstance(goal_batch, list) else goal_batch,
                    step_count=(
                        step_count[0].item()
                        if isinstance(step_count, torch.Tensor)
                        else step_count
                    ),
                )
            else:
                teacher_out = self.teacher(
                    input_ids=batch["input_ids"],
                    attention_mask=batch["attention_mask"],
                    step_count=(
                        step_count if isinstance(step_count, torch.Tensor) else None
                    ),
                    vision_embedding=vision_embedding,
                )

        # Student prediction
        if text_batch is not None and isinstance(text_batch, list):
            student_out = self.student.forward_text(
                observation_text=text_batch[0] if len(text_batch) == 1 else text_batch,
                goal=goal_batch[0] if isinstance(goal_batch, list) else goal_batch,
                step_count=(
                    step_count[0].item()
                    if isinstance(step_count, torch.Tensor)
                    else step_count
                ),
            )
        else:
            student_out = self.student(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                step_count=step_count if isinstance(step_count, torch.Tensor) else None,
                vision_embedding=vision_embedding,
            )

        loss = self.distillation_loss(teacher_out, student_out)
        loss.backward()
        self.optimizer.step()

        return loss.item()

    def save_student(self, path: str):
        """Save the distilled student model."""
        save_path = Path(path)
        save_path.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "model_state": self.student.state_dict(),
                "config": {
                    "encoder_name": getattr(self.student, "encoder_name", "unknown"),
                    "hidden_dim": getattr(self.student, "hidden_dim", 512),
                    "num_layers": getattr(self.student, "num_layers", 3),
                },
            },
            save_path / "student_model.pt",
        )
        logger.info(f"Student model saved to {path}")

    def load_student(self, path: str) -> ProgressEstimator:
        """Load a previously distilled student model."""
        ckpt = torch.load(
            Path(path) / "student_model.pt",
            map_location=self.device,
            weights_only=True,
        )
        self.student.load_state_dict(ckpt["model_state"])
        logger.info(f"Student model loaded from {path}")
        return self.student
