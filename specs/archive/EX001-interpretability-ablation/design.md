# [EX001] 详细设计

## 1. 原则

- **同任务、同预算、同 seed** 才能归因；
- 一次只改变一个因素；
- 成功由验证器判定，不从动作/日志推断；
- 所有图表直接读 JSON，不手工填数。

## 2. 代码改动（仅实验能力）

| 改动 | 目的 |
|------|------|
| `BrowserEnv(perturb_prob)` | E1 概率扰动 |
| `rollout_task(verifier_hints=False)` | E3 观测消融 |
| `evaluate_policy(perturb_prob, verifier_hints)` | 统一评测入口 |
| `scripts/ex001_*.py` | 各实验执行器 |
| `scripts/ex001_figures.py` | 读 JSON 生成图 |

不改变生产默认行为：`perturb_prob=1.0`、`verifier_hints=True`。

## 3. 实验实现

### E1

- 实现：`evaluate_policy` 对 4 个 L1–L2 任务，分别 selector/semantic，`perturb_prob∈{0,.25,.5,.75,1}`；
- 记录：success、steps、raw_invalid、repaired；
- 图：双折线 + 95% Wilson 区间（若样本足够）。

### E2

- 加载语义多适配器；
- flat：按任务选一个 adapter，直接 `rollout_task`，不分解；
- hierarchy：`run_hierarchy`；
- 9 任务，比较按等级成功率。

### E3

- `verifier_hints=False` 时，prompt 不写 `Φ/未完成`；
- 其余完全一致；
- 比较 9 任务与按等级。

### E6

- 读取 AR001–AR006 JSON；
- 将失败归因到最终缺失谓词（优先 `order_placed > cart_contains > ...`）；
- 输出矩阵：AR × 失败阶段。

### E7

- 任务：ev_qty_p3、ev_checkout_p3、ev_multi_p3p4；
- 3 次重复；
- 记录 success、steps、prompt/gen token（从 StepRecord）。

### E8

- CPU：planner 1000 次、verifier 1000 次、HTTP 200 次；
- GPU：语义 SFT 模型 generate 20 次，记录 P50/P95、峰值显存；
- 同时记录 GPU 名称/时钟（nvidia-smi），说明限制。

## 4. 图表

1. `fig_e1_perturb.png`：接口 × 扰动概率成功率。
2. `fig_e2_levels.png`：flat vs hierarchy 按等级。
3. `fig_e3_hints.png`：hints on/off 按等级。
4. `fig_e6_failures.png`：失败阶段堆叠柱。
5. `fig_e7_cost.png`：成功率/步数/token 成本。
6. `fig_e8_hardware.png`：CPU/GPU 延迟对比（对数轴）。

## 5. 报告结构

- 结论先行：每条设计一句话结论；
- 场景化：L1–L5 + 缺货 + 改版；
- 实验细节与原始数据链接；
- 局限与反例。
