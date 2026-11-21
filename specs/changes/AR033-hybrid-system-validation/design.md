# [AR033] 设计

- `step_rl/edge/system.py`：HybridSystem.run_local/run_remote；
- `step_rl/edge/adapters/registry.py`：站点名→adapter，core 不含站点特判；
- 复用 runtime/adapters/console；
- `scripts/ar033_system_eval.py` 分 P0-P4 收集真实结果（P0 local CPU、P1 Console、P2 remote readonly、P3 GPU fallback、P4 evidence/verdict）；
- CPU 30 场景由 AR011 真实套件提供；GPU 兜底用真实 Qwen（model path 入证据）；
- 远程只读只记录真实状态。
