# AR008 观测压缩真实评测（5 个代表任务）

| 条件 | 成功率 | 平均步数 | Prompt tokens | 生成 tokens |
|------|--------|----------|---------------|-------------|
| full | 100.0% | 8.00 | 10009 | 769 |
| decoy-filtered | 100.0% | 8.00 | 9589 | 769 |

Prompt token reduction: **4.2%**

## 决策

- 相关性 top-K 裁剪：60% 成功，回退。
- 历史行压缩：0% 成功，回退。
- 仅移除干扰控件：100% 成功，prompt tokens -4.2%，保留为效率层。
- 30% token 目标未达到；如实记录，不夸大。

## 逐任务

| 任务 | 条件 | 成功 | 步数 | Prompt | Gen |
|------|------|------|------|--------|-----|
| ev_checkout_p3 | full | ✓ | 9 | 2173 | 174 |
| ev_checkout_p3 | pruned | ✓ | 9 | 2103 | 174 |
| ev_checkout_p4 | full | ✓ | 9 | 2198 | 173 |
| ev_checkout_p4 | pruned | ✓ | 9 | 2128 | 173 |
| ev_multi_p3p4 | full | ✓ | 15 | 3667 | 277 |
| ev_multi_p3p4 | pruned | ✓ | 15 | 3527 | 277 |
| ev_qty_p3 | full | ✓ | 5 | 1429 | 104 |
| ev_qty_p3 | pruned | ✓ | 5 | 1359 | 104 |
| ev_search_p3 | full | ✓ | 2 | 542 | 41 |
| ev_search_p3 | pruned | ✓ | 2 | 472 | 41 |
