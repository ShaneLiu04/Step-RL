# AR034 端侧 LLM 自愈技能闭环报告

> 真实 Qwen3-0.6B + 真实 LocalShopServer/Edge；无 mock。

## 对照（同一 remove 任务，seed p3=1）

| 组 | success | fallback | policy steps | skill steps | tokens | 秒 |
|----|---------|----------|--------------|-------------|--------|----|
| baseline #1 | ✓ | ✓ | 4 | 0 | 1142 | 24.75 |
| baseline #2 | ✓ | ✓ | 4 | 0 | 1142 | 24.56 |
| self-heal #1 | ✓ | ✓ | 4 | 0 | 1142 | 24.49 |
| self-heal #2 | ✓ | ✗ | **0** | **4** | **0** | **0.84** |

self-heal #1 注册 `induced_remove`；#2 直接复用技能，0 LLM。
baseline 无自愈，两次均重复 LLM。

## 机制
- LLM fallback 前用 TrajectoryRecorder 包裹真实 env；
- 验证器 success 后，induce_skill + register_induced_skill；
- 可选 learning_path 持久化；
- 只对非内置 operation 自愈，add/search/checkout/update 路径不变。

## 证据
- `outputs/ar034/eval/ar034_results.json`
- `outputs/ar034/induced_skills.json`
- GIF: `docs/images/ar034_demo.gif`（16KB，真实截图帧）

## 真实截图/GIF
GIF 4 帧：baseline #1、baseline #2、self-heal #1、self-heal #2，
对应 policy/token/skill 步数；不是动画伪造。

## 结论
- 自愈闭环成立：一次 LLM 兜底 → 下一次 0 LLM；
- 端侧 0.6B 可以在真实浏览器上完成未覆盖操作并沉淀技能；
- baseline 与自愈组的差异来自真实 token/步数。
