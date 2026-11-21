# [AR028] 增量实现设计

## 1. 总体思路

在 AR027 CTC 上增加订单阶段：

1. planner 识别 transform + checkout + promo；
2. runtime 解析真实目标，先做券门槛预检；
3. 执行 CTC（逐项复核）；
4. 执行 checkout（真实领券/表单/提交）；
5. 验证订单；失败则取消订单并回滚购物车。

## 2. 模块改动

### 2.1 `tasks.py`
- `cart_transform` 的 `predicate_names` 增加 checkout/order/promo 谓词；
- 仅 transform 时仍为 `cart_contains`。

### 2.2 `planner.py`
- `plan_instruction(..., enable_compound=True)`；
- transform 块：`checkout = enable_compound and 含结算/下单`；
- 券：`满X减Y` + checkout + 真实 promo 列表，未知/泛称显式 None；
- `enable_compound=False` 保留 AR027 行为（忽略结算/券）。

### 2.3 `runtime.py`
- `run_task(..., enable_compound=True)`；
- 目标解析后，若 `require_promo`：用真实目录价计算总额，低于门槛立即失败；
- `run_cart_transform`：CTC 后若 `require_checkout`，执行 `checkout_skill(promo)`；
- 订单验证失败：若 `state.order` 存在则 `cancel_order`，再 `_rollback_cart`；
- 成功返回订单、promo、steps；失败返回 `preflight`/`compensated`/`error`。

### 2.4 Demo
- `scripts/ar028_demo_gif.py`：真实 Edge 截图，Pillow 合成 5 帧 GIF；
- 输出 `docs/images/ar028_demo.gif`（约 40KB，适合同步）。

## 3. 关键决策

- **D1 预检先于动作**：券门槛不足时不能先改购物车；否则用户看到半完成状态。
- **D2 订单失败必须取消**：验证失败但 order 已生成时，先 cancel 再回滚。
- **D3 回滚也复核**：恢复数量后读服务端状态，`compensated` 只计真实恢复项。
- **D4 baseline 用 AR027**：`enable_compound=False` 是真实能力缺口，不是 mock。
- **D5 GIF 来自真实运行**：截图来自真实 Edge，订单/券金额来自服务端状态。

## 4. 测试设计

1. planner：transform+checkout、+promo、baseline 仅 transform；
2. 真实 double+checkout：订单 items {p3:2,p4:2}；
3. 真实 double+checkout+满400减50：promo.applied、paid=total−50；
4. 预检失败：满2000减150、total=398，0 动作、cart 不变、order=None；
5. baseline 忽略结算：cart 变换但 order=None；
6. 订单故障：`fault_order_once`，cart 恢复、order=None、compensated=2。

## 5. 风险与对策

| 风险 | 对策 |
|------|------|
| 券门槛按目标价算错 | 用真实目录价 + 目标数量，预检失败零动作 |
| 订单已生成但验证失败 | 先 cancel_order 再回滚 |
| 回滚不完整 | 只恢复 changed 项并逐项复核 |
| 结算失败但购物车已变 | `_rollback_cart` + compensated 审计 |
| 30 场景回退 | AR011 30/30 + edge 181 门禁 |

## 6. 回滚

回退 AR028：去掉 compound planning/checkout/preflight/rollback 与 demo；AR027
CTC 保持。产物保留 `outputs/ar028/`。

## 7. 组合回退规则

A = AR027（AR011 30/30、edge 175）。
1. B = A + AR028；edge 不得新增失败。
2. B 的 AR011 必须 30/30、0 LLM。
3. B 的 COT 必须 3/3；预检/回滚必须显式正确。
4. 全部满足 → v4.17 保留；否则回退并归档负结果。
