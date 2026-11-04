# AR002 记忆与重规划真实评测

| 组合 | 成功率 | 平均步数 | 平均进度 | 重规划次数 |
|------|--------|----------|----------|------------|
| routed_combo_repair | 77.8% | 5.11 | 0.90 | 0 |
| router_memory | 66.7% | 5.11 | 0.79 | 0 |
| router_replan | 66.7% | 5.11 | 0.82 | 3 |

最优组合：**routed_combo_repair**（成功率 77.8%）

## 逐任务（L4/L5）

| 任务 | 组合 | 成功 | 进度 | 步数 | 重规划 |
|------|------|------|------|------|--------|
| ev_checkout_p3 | routed_combo_repair | ✗ | 0.75 | 8 | 0 |
| ev_checkout_p4 | routed_combo_repair | ✓ | 1.00 | 8 | 0 |
| ev_multi_p3p4 | routed_combo_repair | ✗ | 0.38 | 8 | 0 |
| ev_checkout_p3 | router_memory | ✗ | 0.38 | 8 | 0 |
| ev_checkout_p4 | router_memory | ✗ | 0.62 | 8 | 0 |
| ev_multi_p3p4 | router_memory | ✗ | 0.12 | 8 | 0 |
| ev_checkout_p3 | router_replan | ✗ | 0.38 | 8 | 0 |
| ev_checkout_p4 | router_replan | ✗ | 0.62 | 8 | 1 |
| ev_multi_p3p4 | router_replan | ✗ | 0.38 | 8 | 2 |
