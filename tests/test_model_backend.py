"""Unit tests for model backend abstraction."""

from unittest.mock import MagicMock, patch

import pytest

from step_rl.inference.model_backend import (
    GPT4OBackend,
    HuggingFaceBackend,
    PolicyModelBackend,
    VLLMBackend,
    create_backend,
)


class TestModelBackend:
    def test_create_backend_huggingface(self):
        with patch(
            "transformers.AutoModelForCausalLM.from_pretrained"
        ) as mock_model, patch(
            "transformers.AutoTokenizer.from_pretrained"
        ) as mock_tokenizer:
            mock_model.return_value = MagicMock()
            tok = MagicMock()
            tok.pad_token = None
            tok.eos_token = "</s>"
            mock_tokenizer.return_value = tok
            backend = create_backend(
                {
                    "backend": "huggingface",
                    "model_name": "gpt2",
                    "device": "cpu",
                    "dtype": "fp32",
                }
            )
            assert isinstance(backend, HuggingFaceBackend)

    def test_create_backend_unknown(self):
        with pytest.raises(TypeError):
            create_backend({"backend": "unknown"})

    def test_policy_backend_abstract(self):
        with pytest.raises(TypeError):
            PolicyModelBackend()

    @pytest.mark.skip(reason="Requires vllm installation")
    def test_create_backend_vllm(self):
        backend = create_backend({"backend": "vllm", "model_name": "gpt2"})
        assert isinstance(backend, VLLMBackend)

    @pytest.mark.skip(reason="Requires openai API key")
    def test_create_backend_gpt4o(self):
        backend = create_backend({"backend": "gpt4o", "api_key": "test-key"})
        assert isinstance(backend, GPT4OBackend)
