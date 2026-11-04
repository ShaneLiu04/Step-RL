# AR005 跨布局零样本迁移真实评测

| 条件 | 布局 | 接口 | ID churn | 成功率 | 平均步数 | 平均进度 | 非法动作 |
|------|------|------|----------|--------|----------|----------|----------|
| selector_v2 | v2 | selector | 否 | 100.0% | 6.78 | 1.00 | 2 |
| selector_v2_churn | v2 | selector | 是 | 0.0% | 12.00 | 0.00 | 99 |
| semantic_v1 | v1 | semantic | 否 | 100.0% | 6.33 | 1.00 | 0 |
| semantic_v2_churn | v2 | semantic | 是 | 100.0% | 7.89 | 1.00 | 0 |
| semantic_v2_zero_shot | v2 | semantic | 否 | 100.0% | 7.33 | 1.00 | 0 |
