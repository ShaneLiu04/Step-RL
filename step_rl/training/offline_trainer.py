"""Offline RL trainer (DPO-style) from static trajectory datasets."""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

from step_rl.utils.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class OfflineTrajectory:
    """Static trajectory for offline training."""

    observation: str
    action: str
    reward: float
    next_observation: str
    done: bool
    task_goal: str


class OfflineRLDataset(Dataset):
    """Dataset for offline RL.

    Expects a JSON-lines file where each line is a dict with keys:
    ``chosen`` (successful trajectory), ``rejected`` (failed trajectory),
    and optionally ``chosen_labels``, ``rejected_labels`` for pre-tokenized data.

    Parameters
    ----------
    data_path : str
        Path to the ``.jsonl`` dataset file.
    """

    def __init__(self, data_path: str):
        self.data: List[Dict[str, Any]] = []
        path = Path(data_path)
        if not path.exists():
            raise FileNotFoundError(f"Offline dataset not found: {data_path}")
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                self.data.append(json.loads(line))
        logger.info(f"Loaded {len(self.data)} offline trajectories from {data_path}")

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        return self.data[idx]


class OfflineRLTrainer:
    """Train policy from offline trajectory data without environment interaction.

    Supports DPO (Direct Preference Optimization) loss on preference pairs
    extracted from successful vs. failed trajectories.

    Parameters
    ----------
    policy_model : torch.nn.Module
        The trainable policy model.
    ref_model : torch.nn.Module
        The frozen reference model for KL regularization.
    tokenizer : transformers.PreTrainedTokenizer
        Tokenizer for converting text to model inputs.
    config : Dict[str, Any]
        Full Step-RL config dict.
    """

    def __init__(
        self,
        policy_model: nn.Module,
        ref_model: nn.Module,
        tokenizer: Any,
        config: Dict[str, Any],
    ):
        self.policy = policy_model
        self.ref_model = ref_model
        self.tokenizer = tokenizer
        self.config = config
        self.beta = config.get("offline_beta", 0.1)
        self.device = next(policy_model.parameters()).device
        logger.info(f"OfflineRLTrainer initialized (beta={self.beta})")

    # ------------------------------------------------------------------
    # DPO loss
    # ------------------------------------------------------------------

    def _get_logprob(
        self, logits: torch.Tensor, labels: torch.Tensor
    ) -> torch.Tensor:
        """Extract per-token log-probability and sum over sequence.

        Parameters
        ----------
        logits :
            ``(batch, seq_len, vocab_size)`` unnormalized logits.
        labels :
            ``(batch, seq_len)`` token indices.  ``-100`` is ignored.

        Returns
        -------
        torch.Tensor
            ``(batch,)`` summed log-probabilities.
        """
        log_probs = F.log_softmax(logits, dim=-1)
        gathered = log_probs.gather(dim=-1, index=labels.unsqueeze(-1)).squeeze(-1)
        mask = labels.ne(-100)
        return (gathered * mask).sum(dim=-1)

    def dpo_loss(
        self,
        chosen_logits: torch.Tensor,
        rejected_logits: torch.Tensor,
        chosen_labels: torch.Tensor,
        rejected_labels: torch.Tensor,
    ) -> torch.Tensor:
        """Direct Preference Optimization loss.

        Parameters
        ----------
        chosen_logits :
            Policy logits for chosen (successful) sequences.
        rejected_logits :
            Policy logits for rejected (failed) sequences.
        chosen_labels :
            Token labels for chosen sequences.
        rejected_labels :
            Token labels for rejected sequences.

        Returns
        -------
        torch.Tensor
            Scalar DPO loss.
        """
        chosen_logprob = self._get_logprob(chosen_logits, chosen_labels)
        rejected_logprob = self._get_logprob(rejected_logits, rejected_labels)

        with torch.no_grad():
            ref_chosen_logits = self.ref_model(
                input_ids=chosen_labels.ne(-100).long() * chosen_labels
            ).logits
            ref_rejected_logits = self.ref_model(
                input_ids=rejected_labels.ne(-100).long() * rejected_labels
            ).logits
            ref_chosen_logprob = self._get_logprob(ref_chosen_logits, chosen_labels)
            ref_rejected_logprob = self._get_logprob(
                ref_rejected_logits, rejected_labels
            )

        policy_ratio = chosen_logprob - rejected_logprob
        ref_ratio = ref_chosen_logprob - ref_rejected_logprob

        loss = -F.logsigmoid(self.beta * (policy_ratio - ref_ratio)).mean()
        return loss

    # ------------------------------------------------------------------
    # Tokenization helpers
    # ------------------------------------------------------------------

    def _tokenize_pair(
        self, chosen_text: str, rejected_text: str
    ) -> Dict[str, torch.Tensor]:
        """Tokenize a preference pair and pad to the same length."""
        chosen = self.tokenizer(
            chosen_text,
            return_tensors="pt",
            padding="max_length",
            truncation=True,
            max_length=4096,
        )
        rejected = self.tokenizer(
            rejected_text,
            return_tensors="pt",
            padding="max_length",
            truncation=True,
            max_length=4096,
        )
        # Move to device and squeeze batch dim
        return {
            "chosen_input_ids": chosen["input_ids"].squeeze(0).to(self.device),
            "chosen_attention_mask": chosen["attention_mask"]
            .squeeze(0)
            .to(self.device),
            "rejected_input_ids": rejected["input_ids"].squeeze(0).to(self.device),
            "rejected_attention_mask": rejected["attention_mask"]
            .squeeze(0)
            .to(self.device),
        }

    # ------------------------------------------------------------------
    # Training loop
    # ------------------------------------------------------------------

    def train_from_trajectories(
        self,
        dataset_path: str,
        epochs: int = 3,
        batch_size: int = 4,
        learning_rate: float = 1e-5,
    ) -> None:
        """Train from offline trajectory dataset using DPO loss.

        Parameters
        ----------
        dataset_path : str
            Path to ``.jsonl`` file with preference pairs.
        epochs : int
            Number of training epochs.
        batch_size : int
            Per-device batch size.
        learning_rate : float
            AdamW learning rate.
        """
        dataset = OfflineRLDataset(dataset_path)
        dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
        optimizer = torch.optim.AdamW(
            self.policy.parameters(), lr=learning_rate, weight_decay=0.01
        )

        self.policy.train()
        self.ref_model.eval()

        for epoch in range(epochs):
            total_loss = 0.0
            num_batches = 0

            for batch in dataloader:
                # Build preference pairs from successful vs failed trajectories
                chosen_texts = batch.get("chosen", [])
                rejected_texts = batch.get("rejected", [])

                if not chosen_texts or not rejected_texts:
                    logger.warning(
                        "Batch missing 'chosen' or 'rejected' keys; skipping"
                    )
                    continue

                # Tokenize each pair in the batch
                chosen_input_ids, chosen_labels = [], []
                rejected_input_ids, rejected_labels = [], []

                for c, r in zip(chosen_texts, rejected_texts):
                    tokens = self._tokenize_pair(c, r)
                    chosen_input_ids.append(tokens["chosen_input_ids"])
                    chosen_labels.append(tokens["chosen_input_ids"])
                    rejected_input_ids.append(tokens["rejected_input_ids"])
                    rejected_labels.append(tokens["rejected_input_ids"])

                chosen_input_ids = torch.stack(chosen_input_ids)
                rejected_input_ids = torch.stack(rejected_input_ids)

                # Forward pass through policy
                chosen_logits = self.policy(input_ids=chosen_input_ids).logits
                rejected_logits = self.policy(input_ids=rejected_input_ids).logits

                loss = self.dpo_loss(
                    chosen_logits, rejected_logits, chosen_input_ids, rejected_input_ids
                )

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.policy.parameters(), 1.0)
                optimizer.step()

                total_loss += loss.item()
                num_batches += 1

            avg_loss = total_loss / max(num_batches, 1)
            logger.info(f"Epoch {epoch + 1}/{epochs}: avg_loss={avg_loss:.4f}")
