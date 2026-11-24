# [AR034] 设计

- runtime 在 LLM fallback 前用 TrajectoryRecorder 包裹真实 BrowserEnv；
- 成功且 operation 非内置时 induce_skill + register_induced_skill；
- 可选 learning_path 持久化；
- baseline enable_self_healing=False；
- 真实 Qwen 对照 + GIF。
