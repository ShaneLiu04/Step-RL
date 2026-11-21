# [AR033] 设计

- `step_rl/system.py`：HybridSystem.run_local/run_remote；
- 复用 runtime/adapters/console；
- `scripts/ar033_system_eval.py` 分 P0-P5 收集真实结果；
- CPU 30 场景由 AR011 真实套件提供；GPU 兜底用真实 Qwen；
- 远程只读只记录真实状态。
