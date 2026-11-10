# AR018 瞬时故障重试真实评测

| 任务 | 模式 | 成功 | 尝试 | 订单 |
|------|------|------|------|------|
| F1 | single_attempt | ✗ | 1 | [] |
| F1 | retry | ✓ | 2 | [{'id': '4aeebfdfce', 'items': {'p3': 1}, 'status': 'active'}] |
| F2 | single_attempt | ✗ | 1 | [] |
| F2 | retry | ✓ | 2 | [{'id': 'e46d3cc495', 'items': {'p4': 2}, 'status': 'active'}] |
| F3 | single_attempt | ✗ | 1 | [] |
| F3 | retry | ✓ | 2 | [{'id': '59345288bd', 'items': {'p2': 1}, 'status': 'active'}] |

## 结论

- 单次执行遇到一次性 500 后失败。
- Runtime 在同 TaskSpec 上重试一次，真实重置会话后成功。
