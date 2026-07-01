"""Multi-backend model abstraction for Step-RL v3.0.
Supports: Qwen, Llama, Mistral, GPT-4o (API-based), vLLM."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class PolicyModelBackend(ABC):
    @abstractmethod
    def generate(self, prompts: List[str], **kwargs) -> List[str]: ...

    @abstractmethod
    def forward(self, inputs: Dict[str, torch.Tensor]) -> torch.Tensor: ...

    @abstractmethod
    def save(self, path: str): ...

    @abstractmethod
    def load(self, path: str): ...


class HuggingFaceBackend(PolicyModelBackend):
    def __init__(self, model_name: str, device: str = "cuda", dtype: str = "bf16"):
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        self.model_name = model_name
        torch_dtype = torch.bfloat16 if dtype == "bf16" and torch.cuda.is_bf16_supported() else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name, torch_dtype=torch_dtype, trust_remote_code=True, device_map="auto"
        )

    def generate(self, prompts: List[str], max_new_tokens: int = 256, temperature: float = 0.7, **kwargs) -> List[str]:
        inputs = self.tokenizer(prompts, return_tensors="pt", padding=True, truncation=True, max_length=4096)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs, max_new_tokens=max_new_tokens, temperature=temperature, do_sample=True, **kwargs
            )
        return self.tokenizer.batch_decode(outputs, skip_special_tokens=True)

    def forward(self, inputs: Dict[str, torch.Tensor]) -> torch.Tensor:
        return self.model(**inputs)

    def save(self, path: str):
        self.model.save_pretrained(path)
        self.tokenizer.save_pretrained(path)

    def load(self, path: str):
        self.model = AutoModelForCausalLM.from_pretrained(path, trust_remote_code=True, device_map="auto")
        self.tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=True)


class VLLMBackend(PolicyModelBackend):
    def __init__(self, model_name: str, tensor_parallel_size: int = 1, dtype: str = "bfloat16"):
        try:
            from vllm import LLM, SamplingParams
        except ImportError:
            raise ImportError("vllm is not installed. Install with: pip install vllm")
        self.llm = LLM(
            model=model_name, tensor_parallel_size=tensor_parallel_size,
            dtype=dtype, gpu_memory_utilization=0.9, max_model_len=4096,
        )
        self.sampling_params = SamplingParams(temperature=0.7, max_tokens=256, top_p=0.9)

    def generate(self, prompts: List[str], **kwargs) -> List[str]:
        from vllm import SamplingParams
        params = SamplingParams(**{**self.sampling_params.__dict__, **kwargs})
        outputs = self.llm.generate(prompts, params)
        return [o.outputs[0].text for o in outputs]

    def forward(self, inputs: Dict[str, torch.Tensor]) -> torch.Tensor:
        raise NotImplementedError("vLLM does not support direct forward pass")

    def save(self, path: str): pass
    def load(self, path: str): pass


class GPT4OBackend(PolicyModelBackend):
    """API-based backend for OpenAI GPT-4o."""
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        import os
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model

    async def generate(self, prompts: List[str], **kwargs) -> List[str]:
        results = []
        for prompt in prompts:
            resp = await self.client.chat.completions.create(
                model=self.model, messages=[{"role": "user", "content": prompt}], max_tokens=256, **kwargs
            )
            results.append(resp.choices[0].message.content)
        return results

    def forward(self, inputs: Dict[str, torch.Tensor]) -> torch.Tensor:
        raise NotImplementedError("API backend does not support forward pass")

    def save(self, path: str): pass
    def load(self, path: str): pass


def create_backend(config: Dict[str, Any]) -> PolicyModelBackend:
    backend_type = config.get("backend", "huggingface")
    cfg = {k: v for k, v in config.items() if k != "backend"}
    if backend_type == "vllm":
        return VLLMBackend(**cfg)
    elif backend_type == "gpt4o":
        return GPT4OBackend(**cfg)
    return HuggingFaceBackend(**cfg)
