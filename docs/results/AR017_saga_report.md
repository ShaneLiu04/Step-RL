# AR017 Saga 补偿真实评测

| 场景 | 模式 | 成功 | 订单历史 |
|------|------|------|----------|
| S1_p3_then_p4_oos | no_compensation | ✗ | [{'id': 'c6fb8cc5c9', 'items': {'p3': 1}, 'status': 'active'}] |
| S1_p3_then_p4_oos | saga | ✓ | [{'id': '6fce4ad940', 'items': {'p3': 1}, 'status': 'cancelled'}] |
| S2_p2_then_p3_oos | no_compensation | ✗ | [{'id': '5c82381193', 'items': {'p2': 1}, 'status': 'active'}] |
| S2_p2_then_p3_oos | saga | ✓ | [{'id': 'a9cb5b0c98', 'items': {'p2': 1}, 'status': 'cancelled'}] |

## 结论

- 第二单因真实库存 0 失败；无补偿时第一单保持 active，验证失败。
- Saga 在失败后取消已成功订单，全部订单 cancelled，验证成功。
