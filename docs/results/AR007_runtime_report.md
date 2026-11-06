# AR007 闭环重规划真实评测

| 场景 | 模式 | 成功 | 尝试 | 重规划 | 步数 | 目标变化 |
|------|------|------|------|--------|------|----------|
| D1_stock_substitution | baseline | ✗ | 1 | 否 | 18 | {'p4': 2} |
| D1_stock_substitution | supervisor | ✓ | 2 | 是 | 27 | {'p4': 2} -> {'p2': 2} |
| D2_price_budget | baseline | ✗ | 1 | 否 | 18 | {'p3': 1} |
| D2_price_budget | supervisor | ✓ | 2 | 是 | 27 | {'p3': 1} -> {'p2': 1} |
| static:买最便宜的商品并完成结算 | supervisor_static | ✓ | 1 | 否 | 9 | {'p2': 1} |
| static:买两件USB-C数据线并 | supervisor_static | ✓ | 1 | 否 | 9 | {'p2': 2} |
| static:预算650元，买无线充电 | supervisor_static | ✓ | 1 | 否 | 15 | {'p3': 1, 'p4': 1} |
