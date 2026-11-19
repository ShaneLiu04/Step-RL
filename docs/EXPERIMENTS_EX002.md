# Step-RL 全架构压力实验（EX002）

> 目标：不是再刷一个单 AR 分数，而是验证 AR001–AR026 组合后的**鲁棒性、可解释性、
> 组合冲突与代价**。所有实验基于真实 HTTP 商城 + 系统 Edge + 真实模型/线程执行。

**执行状态：已完成 E1–E8。完整报告与 6 张图见
`docs/results/EX002_report.md`。**

## 1. 研究问题

| 编号 | 问题 | 相关 AR |
|------|------|---------|
| RQ1 | DOM churn 下语义接口是否仍可执行？ | AR004/005 |
| RQ2 | 层级分解是否仍优于扁平路由？ | AR003 |
| RQ3 | 验证器观测在长链路中贡献多大？ | AR001/003 |
| RQ4 | v3 异构控件是否造成能力缺口？ | AR005/026 |
| RQ5 | 观测缓存是否真的降低开销且不回退？ | AR008/025 |
| RQ6 | 并发/注册表压力下是否串扰或损坏？ | AR012/021/024 |
| RQ7 | 故障/补偿/重试/长链路是否真实生效？ | AR016–018 |
| RQ8 | 全部 AR 组合后是否保持 30/30、0 LLM？ | AR001–026 |

## 2. 实验矩阵

| 实验 | 设置 | 指标 | 产物 |
|------|------|------|------|
| E1 接口压力 | selector vs semantic × 扰动 0/0.25/0.5/0.75/1.0；4 任务 | 成功率、非法动作 | `outputs/ex001/e1_perturb.json` |
| E2 层级压力 | 扁平路由 vs 层级；9 任务 | 成功率、失败任务 | `outputs/ex001/e2_flat.json` |
| E3 验证器消融 | Φ/missing on/off；9 任务 | 成功率、步数 | `outputs/ex001/e3_hints_off.json` |
| E4 布局异构 | v1/v2 30 场景；v3 固定 vs LASC | 成功率、LLM 步 | `outputs/ar026/eval/` |
| E5 观测压力 | 旧 4 往返 vs AR025 AOC；30 场景 | 调用、往返、耗时、缓存命中 | `outputs/ar025/` |
| E6 并发压力 | 4 会话 / 4 失败留痕 / 10×12 写者；AR012 并发 | 成功、串扰、损坏、并行比 | `outputs/ar024/`、`outputs/ar012/` |
| E7 故障长链路 | AR016/17/18 baseline vs 组合 | 成功任务数 | `outputs/ar016–18/` |
| E8 组合门禁 | AR011 30 场景 + edge 套件 | 成功率、LLM、tokens、测试数 | `outputs/ar011/`、`outputs/ex002/summary.json` |

## 3. 场景化解读框架

| 场景 | 关键设计 | 观察点 |
|------|----------|--------|
| 搜索/加购 | 语义接口 + SFT | churn 后 selector 是否失效 |
| 数量控制 | VGDP + LASC 步进器 | 无 input 控件能否改量 |
| 结算/长链路 | 验证器观测 + 层级 | 移除 hints 后退化位置 |
| 页面改版 | v3 无 id/searchbox | 固定技能 vs LASC |
| 观测开销 | 单往返 + 修订号缓存 | 往返/耗时下降是否伴随回退 |
| 并发服务 | AR024 锁 + 原子写 | 失败是否精确留痕 |
| 故障/补偿 | AR016–18 | baseline 0 是否转为全成功 |

## 4. 指标定义

- **成功率**：原任务验证器所有谓词满足；
- **非法动作**：选择器元素不存在或动作被白名单拒绝；
- **往返数**：Playwright 浏览器 round-trip 计数（AR025 metrics）；
- **缓存命中**：DOM 修订号/URL/doc 未变且 state 实时；
- **并发并行比**：逐会话耗时和 / 并发墙钟；
- **故障成功数**：AR016/17/18 每个模式下真实成功任务数。

## 5. 复现

```powershell
$env:PYTHONPATH="D:\agentRL\Step-RL"
python scripts/ex001_e1_perturb.py
python scripts/ex001_e2_flat.py
python scripts/ex001_e3_hints.py
python scripts/ar011_eval.py
python scripts/ar024_eval.py
python scripts/ar025_baseline_probe.py
python scripts/ar025_eval.py
python scripts/ar026_eval.py
python scripts/ex002_summary.py
python scripts/ex002_figures.py
```

## 6. 边界

- E1 样本量 n=4，斜率不稳健；0.75/1.0 的 0% vs 100% 稳健；
- E3 是推理期消融，不是重训练消融；
- AR024 边界为单进程多会话，不含跨进程/多机；
- v3 是真实 DOM/JS 自建站点，结论不外推到所有公网网站。
