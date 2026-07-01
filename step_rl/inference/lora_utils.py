"""LoRA merge and optimization utilities."""
from pathlib import Path
from peft import PeftModel
from transformers import AutoModelForCausalLM


def merge_lora_weights(base_model_path: str, adapter_path: str, output_path: str):
    """Merge LoRA adapter into base model and save."""
    model = AutoModelForCausalLM.from_pretrained(base_model_path, trust_remote_code=True, device_map="auto")
    model = PeftModel.from_pretrained(model, adapter_path)
    model = model.merge_and_unload()
    Path(output_path).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_path)
    return output_path
