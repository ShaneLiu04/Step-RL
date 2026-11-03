# AR001 真实评测报告

- 时间：2026-11-04 01:18:00
- 平台：Windows-10-10.0.26200-SP0
- 模型：`C:\Users\l30086046\.cache\huggingface\hub\models--Qwen--Qwen3-0.6B-Base\snapshots\main`
- 最大步数：8

## 指标对比

| 组合 | 修复 | 成功率 | 平均步数 | 平均进度 | 原始非法率 | 修复率 |
|------|------|--------|----------|----------|------------|--------|
| sft | ✗ | 44.4% | 5.78 | 0.76 | 0.0% | 0.0% |
| sft_repair | ✓ | 55.6% | 5.78 | 0.79 | 55.6% | 44.4% |
| sparse_grpo_repair | ✓ | 55.6% | 5.78 | 0.83 | 55.6% | 55.6% |
| vgdp_grpo_repair | ✓ | 66.7% | 5.33 | 0.85 | 33.3% | 11.1% |

## 组合决策

最优组合：**vgdp_grpo_repair**（成功率 66.7%）

回退规则：按 `sft → sft_repair → sparse_grpo_repair → vgdp_grpo_repair`
依次比较，只有严格不劣于当前最优才晋级；否则保留上一最优。

## 逐任务结果

| 任务 | 等级 | 成功 | 进度 | 步数 | 原始非法 | 修复 |
|------|------|------|------|------|----------|------|
| sft/ev_search_p3 | L1 | ✓ | 1.00 | 2 | 0 | 0 |
| sft/ev_search_p4 | L1 | ✓ | 1.00 | 2 | 0 | 0 |
| sft/ev_add_p4 | L2 | ✓ | 1.00 | 4 | 0 | 0 |
| sft/ev_add_p3 | L2 | ✓ | 1.00 | 4 | 0 | 0 |
| sft/ev_qty_p3 | L3 | ✗ | 0.67 | 8 | 0 | 0 |
| sft/ev_qty_p4 | L3 | ✗ | 0.67 | 8 | 0 | 0 |
| sft/ev_checkout_p4 | L4 | ✗ | 0.75 | 8 | 0 | 0 |
| sft/ev_checkout_p3 | L4 | ✗ | 0.38 | 8 | 0 | 0 |
| sft/ev_multi_p3p4 | L5 | ✗ | 0.38 | 8 | 0 | 0 |
| sft_repair/ev_search_p3 | L1 | ✓ | 1.00 | 2 | 0 | 0 |
| sft_repair/ev_search_p4 | L1 | ✓ | 1.00 | 2 | 0 | 0 |
| sft_repair/ev_add_p4 | L2 | ✓ | 1.00 | 4 | 0 | 0 |
| sft_repair/ev_add_p3 | L2 | ✓ | 1.00 | 4 | 0 | 0 |
| sft_repair/ev_qty_p3 | L3 | ✗ | 0.67 | 8 | 2 | 1 |
| sft_repair/ev_qty_p4 | L3 | ✗ | 0.67 | 8 | 2 | 2 |
| sft_repair/ev_checkout_p4 | L4 | ✓ | 1.00 | 8 | 2 | 2 |
| sft_repair/ev_checkout_p3 | L4 | ✗ | 0.38 | 8 | 4 | 0 |
| sft_repair/ev_multi_p3p4 | L5 | ✗ | 0.38 | 8 | 3 | 1 |
| sparse_grpo_repair/ev_search_p3 | L1 | ✓ | 1.00 | 2 | 0 | 0 |
| sparse_grpo_repair/ev_search_p4 | L1 | ✓ | 1.00 | 2 | 0 | 0 |
| sparse_grpo_repair/ev_add_p4 | L2 | ✓ | 1.00 | 4 | 0 | 0 |
| sparse_grpo_repair/ev_add_p3 | L2 | ✓ | 1.00 | 4 | 0 | 0 |
| sparse_grpo_repair/ev_qty_p3 | L3 | ✗ | 0.67 | 8 | 2 | 1 |
| sparse_grpo_repair/ev_qty_p4 | L3 | ✗ | 0.67 | 8 | 2 | 2 |
| sparse_grpo_repair/ev_checkout_p4 | L4 | ✓ | 1.00 | 8 | 2 | 2 |
| sparse_grpo_repair/ev_checkout_p3 | L4 | ✗ | 0.75 | 8 | 2 | 2 |
| sparse_grpo_repair/ev_multi_p3p4 | L5 | ✗ | 0.38 | 8 | 2 | 1 |
| vgdp_grpo_repair/ev_search_p3 | L1 | ✓ | 1.00 | 2 | 0 | 0 |
| vgdp_grpo_repair/ev_search_p4 | L1 | ✓ | 1.00 | 2 | 0 | 0 |
| vgdp_grpo_repair/ev_add_p4 | L2 | ✓ | 1.00 | 5 | 0 | 0 |
| vgdp_grpo_repair/ev_add_p3 | L2 | ✓ | 1.00 | 5 | 0 | 0 |
| vgdp_grpo_repair/ev_qty_p3 | L3 | ✓ | 1.00 | 5 | 0 | 0 |
| vgdp_grpo_repair/ev_qty_p4 | L3 | ✓ | 1.00 | 5 | 0 | 0 |
| vgdp_grpo_repair/ev_checkout_p4 | L4 | ✗ | 0.62 | 8 | 2 | 0 |
| vgdp_grpo_repair/ev_checkout_p3 | L4 | ✗ | 0.62 | 8 | 2 | 0 |
| vgdp_grpo_repair/ev_multi_p3p4 | L5 | ✗ | 0.38 | 8 | 3 | 1 |
