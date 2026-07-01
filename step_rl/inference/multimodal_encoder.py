"""Multimodal observation encoder (text + vision fusion)."""

import torch
import torch.nn as nn
from typing import Optional, Dict, Any
from pathlib import Path


class MultimodalObservationEncoder(nn.Module):
    """Encode both text DOM and screenshot for richer state representation."""

    def __init__(self, text_dim: int, vision_dim: int = 512, fusion_dim: int = 512):
        super().__init__()
        self.text_dim = text_dim
        self.vision_dim = vision_dim
        self.fusion_dim = fusion_dim

        # Fusion layer
        self.fusion = nn.Sequential(
            nn.Linear(text_dim + vision_dim, fusion_dim),
            nn.LayerNorm(fusion_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
        )

    def forward(
        self,
        text_embedding: torch.Tensor,
        vision_embedding: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        if vision_embedding is None:
            return text_embedding

        # Ensure vision embedding matches expected dimension
        if vision_embedding.size(-1) != self.vision_dim:
            vision_embedding = nn.functional.linear(
                vision_embedding,
                torch.randn(
                    vision_embedding.size(-1),
                    self.vision_dim,
                    device=vision_embedding.device,
                ),
            )

        combined = torch.cat([text_embedding, vision_embedding], dim=-1)
        return self.fusion(combined)


class CLIPVisionEncoder:
    """CLIP-based vision encoder for screenshots."""

    def __init__(
        self, model_name: str = "openai/clip-vit-base-patch32", device: str = "cuda"
    ):
        self.device = device if torch.cuda.is_available() else "cpu"
        try:
            from transformers import CLIPProcessor, CLIPModel

            self.processor = CLIPProcessor.from_pretrained(model_name)
            self.model = CLIPModel.from_pretrained(model_name).to(self.device)
            self.model.eval()
        except ImportError:
            raise ImportError(
                "transformers with CLIP support required. Install: pip install transformers[torch]"
            )

    def encode(self, image_path_or_pil) -> torch.Tensor:
        """Encode image to feature vector."""
        inputs = self.processor(images=image_path_or_pil, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            features = self.model.get_image_features(**inputs)
        return features


class Qwen2VLEncoder:
    """Qwen2-VL vision encoder (better for Chinese web content)."""

    def __init__(
        self, model_name: str = "Qwen/Qwen2-VL-7B-Instruct", device: str = "cuda"
    ):
        self.device = device if torch.cuda.is_available() else "cpu"
        try:
            from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

            self.processor = AutoProcessor.from_pretrained(model_name)
            self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                model_name, device_map="auto", torch_dtype=torch.bfloat16
            )
            self.model.eval()
        except ImportError:
            raise ImportError(
                "Qwen2-VL requires latest transformers. Install: pip install transformers -U"
            )

    def encode(self, image_path_or_pil) -> torch.Tensor:
        """Encode image to feature vector."""
        messages = [
            {
                "role": "user",
                "content": [{"type": "image", "image": image_path_or_pil}],
            }
        ]
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(
            text=[text], images=[image_path_or_pil], return_tensors="pt"
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self.model(**inputs, output_hidden_states=True)
            # Use last hidden state mean pooling
            features = outputs.hidden_states[-1].mean(dim=1)
        return features


def create_vision_encoder(config: Dict[str, Any]):
    """Factory for vision encoder."""
    encoder_type = config.get("vision_encoder", "clip")
    if encoder_type == "qwen2vl":
        return Qwen2VLEncoder(**config)
    return CLIPVisionEncoder(**config)
