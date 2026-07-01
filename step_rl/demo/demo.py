"""
Demo UI for Step-RL v2.0
- Gradio interface for task input and live agent observation
- Real-time action display with reasoning chain
- Human correction and feedback collection
"""

import argparse
import asyncio
import json
import os
from typing import Any, Dict, List, Optional

import gradio as gr
import torch
import yaml
from transformers import AutoTokenizer

from step_rl.environment.grounding_validator import GroundingValidator
from step_rl.environment.playwright_env import Action, Observation, PlaywrightWebEnv
from step_rl.inference import HuggingFaceBackend, VLLMBackend, create_backend


class StepRLDemo:
    """Interactive demo for Step-RL Agent."""

    def __init__(self, config: Dict[str, Any], policy_path: str, device: str = "cuda"):
        self.config = config
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")

        model_cfg = config.get("model", {})
        backend_type = model_cfg.get("backend", "huggingface")

        # 构建 backend 配置，支持通过 config 切换后端
        backend_cfg = {
            "model_name": model_cfg.get("base_model", "Qwen/Qwen3-8B-Instruct"),
            "device": device,
            "dtype": model_cfg.get("dtype", "bf16"),
        }

        # 对于 vLLM 后端，如果 policy_path 指向包含模型权重的目录，则直接使用它
        if backend_type == "vllm" and os.path.isdir(policy_path):
            has_weights = any(
                f.endswith((".safetensors", ".bin", ".pt"))
                for f in os.listdir(policy_path)
            )
            if has_weights:
                backend_cfg["model_name"] = policy_path
                backend_cfg["tensor_parallel_size"] = model_cfg.get(
                    "tensor_parallel_size", 1
                )
                backend_cfg["dtype"] = model_cfg.get("dtype", "bfloat16")

        # 对于 GPT-4o 后端
        if backend_type == "gpt4o":
            backend_cfg["api_key"] = model_cfg.get("api_key")
            backend_cfg["model"] = model_cfg.get("base_model", "gpt-4o")

        self.backend = create_backend(backend_cfg)

        # 获取 tokenizer（HF 后端直接使用内置的；其他后端单独加载）
        if hasattr(self.backend, "tokenizer"):
            self.tokenizer = self.backend.tokenizer
        else:
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_cfg.get("base_model", "Qwen/Qwen3-8B-Instruct"),
                trust_remote_code=True,
            )
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token

        # 对于 HF 后端，如果 policy_path 是 adapter 目录，则加载 LoRA adapter
        if backend_type == "huggingface" and os.path.isdir(policy_path):
            if os.path.exists(os.path.join(policy_path, "adapter_config.json")):
                self.backend.load(policy_path)

        self.env = PlaywrightWebEnv(**config["environment"])
        self.grounding = GroundingValidator(**config["reward"]["grounding"])
        self.max_steps = config["training"]["max_steps_per_episode"]

        self._history: List[Dict[str, Any]] = []
        self._current_obs: Optional[Observation] = None
        self._task_goal: str = ""

    async def start_task(self, task_goal: str, start_url: str = "") -> str:
        self._task_goal = task_goal
        self._history = []
        self._current_obs = await self.env.reset(task_goal, start_url or None)
        return self._format_observation(self._current_obs)

    async def step_agent(self) -> str:
        if self._current_obs is None:
            return "请先输入任务并点击开始。"

        prompt = self._build_prompt()
        action_dict = await self._generate_action(prompt)

        # Grounding validation
        valid, r_ground, corrected, msg = await self.grounding.validate_and_correct(
            self.env.page, action_dict["action"], action_dict.get("params", {})
        )
        if corrected:
            action_dict = corrected

        action = Action.from_json(json.dumps(action_dict))
        success, info = await self.env.execute_action(action)

        self._history.append(
            {
                "thought": action_dict.get("thought", ""),
                "action": action_dict["action"],
                "params": action_dict.get("params", {}),
                "grounding_valid": valid,
                "grounding_msg": msg,
                "execute_success": success,
            }
        )

        self._current_obs = await self.env.get_observation()
        return self._format_step_result(action_dict, valid, msg, success, info)

    async def step_manual(self, action_json: str) -> str:
        try:
            action_dict = json.loads(action_json)
        except json.JSONDecodeError:
            return "JSON 格式错误，请检查输入。"

        action = Action.from_json(action_json)
        success, info = await self.env.execute_action(action)
        self._history.append(
            {
                "thought": action_dict.get("thought", "人工干预"),
                "action": action_dict["action"],
                "params": action_dict.get("params", {}),
                "grounding_valid": True,
                "grounding_msg": "manual",
                "execute_success": success,
            }
        )
        self._current_obs = await self.env.get_observation()
        return f"手动执行: {action_json}\n结果: {info}\n\n{self._format_observation(self._current_obs)}"

    def _build_prompt(self) -> str:
        history_str = (
            "\n".join(
                [
                    f"{i+1}. [{h['action']}] {h['thought']}"
                    for i, h in enumerate(self._history[-10:])
                ]
            )
            if self._history
            else "无"
        )
        return (
            f"你是一位 Web 自动化助手。请根据任务目标和当前页面状态，生成下一步操作。\n"
            f"任务: {self._task_goal}\n"
            f"历史操作:\n{history_str}\n"
            f"当前页面 URL: {self._current_obs.url}\n"
            f"当前页面标题: {self._current_obs.title}\n"
            f"当前页面:\n{self._current_obs.text}\n"
            f"请输出 JSON 格式的思考与动作。"
        )

    async def _generate_action(self, prompt: str) -> Dict[str, Any]:
        # 使用 backend 进行生成，根据不同后端类型处理
        if isinstance(self.backend, HuggingFaceBackend):
            inputs = self.tokenizer(
                prompt, return_tensors="pt", truncation=True, max_length=4096
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            with torch.no_grad():
                generated = self.backend.model.generate(
                    **inputs,
                    max_new_tokens=256,
                    do_sample=True,
                    temperature=0.7,
                    top_p=0.9,
                    pad_token_id=self.tokenizer.pad_token_id,
                )
            response_ids = generated[0, inputs["input_ids"].shape[1] :]
            response_text = self.tokenizer.decode(
                response_ids, skip_special_tokens=True
            )
        else:
            # vLLM 或 GPT-4o 后端，generate 返回纯文本
            import inspect

            kwargs = {"temperature": 0.7, "top_p": 0.9}
            if isinstance(self.backend, VLLMBackend):
                kwargs = {"temperature": 0.7, "top_p": 0.9}
            if inspect.iscoroutinefunction(self.backend.generate):
                responses = await self.backend.generate([prompt], **kwargs)
            else:
                responses = self.backend.generate([prompt], **kwargs)
            response_text = responses[0]

        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return {
                "thought": "解析失败",
                "action": "wait",
                "params": {"duration_ms": 1000},
            }

    def _format_observation(self, obs: Observation) -> str:
        return f"URL: {obs.url}\n标题: {obs.title}\n\n页面内容:\n{obs.text[:2000]}"

    def _format_step_result(
        self, action: Dict, valid: bool, msg: str, success: bool, info: Dict
    ) -> str:
        lines = [
            "=== Agent 决策 ===",
            f"思考: {action.get('thought', '')}",
            f"动作: {action['action']}",
            f"参数: {json.dumps(action.get('params', {}), ensure_ascii=False)}",
            f"Grounding: {'通过' if valid else '失败'} | {msg}",
            f"执行: {'成功' if success else '失败'} | {info}",
            "",
            "=== 当前页面 ===",
            self._format_observation(self._current_obs),
        ]
        return "\n".join(lines)

    async def close(self):
        await self.env.stop()


def build_gradio_ui(demo: StepRLDemo) -> gr.Blocks:
    with gr.Blocks(title="Step-RL v2.0 Demo") as app:
        gr.Markdown("# Step-RL v2.0: LLM Agent 长链路决策优化系统")
        gr.Markdown("输入任务指令，观察 Agent 的推理与操作过程。可随时人工干预。")

        with gr.Row():
            with gr.Column(scale=1):
                task_input = gr.Textbox(
                    label="任务指令",
                    placeholder="例如：在京东搜索 iPhone 15 并加入购物车",
                )
                url_input = gr.Textbox(
                    label="起始 URL (可选)", placeholder="https://..."
                )
                start_btn = gr.Button("开始任务", variant="primary")
                step_btn = gr.Button("Agent 自动执行一步")
                manual_input = gr.Textbox(
                    label="手动动作 (JSON)",
                    placeholder='{"thought":"人工干预","action":"click","params":{"element_text":"立即购买"}}',
                )
                manual_btn = gr.Button("执行手动动作")

            with gr.Column(scale=2):
                output_box = gr.Textbox(label="状态与日志", lines=30, interactive=False)

        start_btn.click(
            fn=lambda t, u: asyncio.run(demo.start_task(t, u)),
            inputs=[task_input, url_input],
            outputs=output_box,
        )
        step_btn.click(
            fn=lambda: asyncio.run(demo.step_agent()),
            inputs=[],
            outputs=output_box,
        )
        manual_btn.click(
            fn=lambda a: asyncio.run(demo.step_manual(a)),
            inputs=[manual_input],
            outputs=output_box,
        )

    return app


def main():
    parser = argparse.ArgumentParser(description="Step-RL Demo")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument(
        "--policy", type=str, required=True, help="Path to policy adapter or checkpoint"
    )
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument(
        "--share", action="store_true", help="Create public Gradio link"
    )
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    demo = StepRLDemo(config, args.policy)

    try:
        app = build_gradio_ui(demo)
        app.launch(server_port=args.port, share=args.share)
    finally:
        asyncio.run(demo.close())


if __name__ == "__main__":
    main()
