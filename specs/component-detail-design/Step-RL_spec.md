# Step-RL 组件详细设计（基线 v3.1）

| 字段 | 内容 |
|------|------|
| 组件 | Step-RL |
| 版本 | 3.1（AR001 之前基线） |
| 日期 | 2026-11-03 |
| 状态 | Active |

## 1. 组件职责

Step-RL 是面向 Web 自动化 Agent 的长链路强化学习框架，覆盖：
观测 → 动作生成 → 动作执行/校验 → 稠密奖励 → 策略优化 → 评测部署。

## 2. 现有模块与真实状态

| 模块 | 路径 | 状态 |
|------|------|------|
| Web 环境 | `step_rl/environment/playwright_env.py` | 真实 Playwright 实现，但 finish 无任务校验 |
| 动作校验 | `step_rl/environment/grounding_validator.py` | 规则式奖励，缓存键缺 action 类型 |
| 训练基类 | `step_rl/training/base_trainer.py` | 自定义循环，log-prob 对齐有误 |
| PPO/GRPO | `step_rl/training/*_trainer.py` | 未接 TRL，config 与构造器不匹配 |
| 奖励模型 | `step_rl/reward/progress_estimator.py` | 可用，但标签来源为合成数据 |
| 评测 | `step_rl/evaluation/benchmark.py` | 支持 `--mock` 随机结果，不能作为证据 |
| 测试 | `tests/` | 105 个函数，未覆盖训练器/真实环境 |

## 3. 设计约束

1. **真实性优先**：任何用于结论的指标必须来自真实环境执行，不允许随机数或硬编码。
2. **端侧优先**：以 0.5B–1.5B 模型、16GB 显存为第一目标。
3. **可复现**：固定种子；数据、checkpoint、评测 JSON 全部落盘。
4. **可回退**：创新组合必须在留出集上优于上一最优组合，否则回退。
5. **安全**：动作白名单、URL 白名单、选择器转义、执行超时。

## 4. AR001 的插入点

新增独立子包 `step_rl/edge/`，不改动已验证的底层工具模块，避免与旧训练器耦合：

```
step_rl/edge/
  site.py        # 真实本地商城（HTTP + 服务端状态）
  tasks.py       # 任务规格与训练/留出划分
  verifier.py    # 可执行稠密进度 Φ(s)
  browser.py     # Playwright(msedge) 真实浏览器环境
  expert.py      # 脚本专家真实交互采集轨迹
  policy.py      # Prompt / JSON 解析 / DOM 接地修复
  sft.py         # LoRA 监督微调
  rollout.py     # 真实轨迹采样
  step_grpo.py   # 步级 GRPO + VGDP
  evaluate.py    # 真实评测矩阵
```

## 5. 既有缺陷处理策略

AR001 必须修复会阻断真实实验的缺陷（配置映射、任务注册、finish 校验、KL 返回值）；其余历史 trainer 的深度重构放入后续 AR，避免一次变更过大。
