# [AR028] 购物车→订单事务需求设计说明书

| 字段 | 内容 |
|------|------|
| AR 编号 | AR028 |
| 主题 | cart-to-order-transaction |
| 关联 | EX002 E7、AR027 CTC、AR023 券约束 |
| 日期 | 2026-11-19 |
| 状态 | Draft |

## 1. 背景与目标

AR027 已把购物车整体变换事务化，但复合指令“把所有商品加倍，并用满400减50结算”
仍会被旧 planner 当作**只改变购物车**：忽略结算与优惠券，用户期望失败。真实
用户不会把“改购物车”和“下单”拆成两次指令。

目标：AR028 把 **变换 → 优惠券预检 → 结算** 编译为一条真实事务：

- baseline（AR027 仅变换）0/3；
- COT 3/3、0 LLM；
- 券门槛不足时在**任何动作前**失败，不改变购物车；
- 结算/订单验证失败时取消订单并把购物车回滚到原数量。

## 2. 范围

**In Scope：**
- `planner.py`：transform 指令识别 `结算/下单` 与 `满X减Y`，生成复合 TaskSpec；
- `runtime.py`：券门槛预检、变换后真实 checkout、订单失败取消+购物车回滚；
- `tasks.py`：cart_transform 的谓词包含 checkout/order/promo；
- 真实测试/评测/GIF 演示/README/REPRODUCTION/归档/Gitee。

**Out of Scope：** 跨会话订单事务、退款、支付网关、任意自然语言解析。

## 3. 功能需求

### FR1 复合规划
- transform + “结算/下单” → `require_checkout=True`；
- 提及 `满X减Y` 且结算 → 对照真实 promo 列表；未知/泛称/无结算显式 None；
- `enable_compound=False` 保留 AR027 仅变换，作为真实 baseline。

### FR2 券门槛预检
- 从真实 cart 计算目标数量，再按真实目录价计算总额；
- 总额 < 券门槛 → 在**任何动作前**返回失败，cart/order 不变；
- 预检失败必须显式 `preflight=True`、错误含 total/threshold。

### FR3 变换 + 结算
- 先执行 AR027 CTC（逐项复核）；
- 再执行 checkout 技能（含真实领券/提交订单）；
- 最终用验证器检查 `order_placed` 与 `order_promo_applied`。

### FR4 失败回滚
- 订单失败/验证失败：若已有 order 则真实取消；
- 已改购物车项按原数量恢复并复核；
- 返回 `compensated` 与显式错误，不伪装成功。

### FR5 Demo
- 真实 Edge 录屏截图生成 GIF，展示购物车→事务→结算→订单成功；
- GIF 必须来自真实运行，不能用静态伪造。

## 4. 非功能需求

| 类型 | 要求 |
|------|------|
| 真实性 | 真实 HTTP/Edge；订单/券来自服务端 |
| 可靠性 | 预检失败零动作；订单失败回滚 |
| 兼容 | AR011 30/30、edge 零回退 |
| 成本 | 0 LLM、0 prompt tokens |

## 5. 验收标准

- baseline 0/3，COT 3/3，0 LLM；
- 券单 total=1196 / paid=1146、promo.applied=true；
- 预检失败 cart 原值、order=None、steps=0；
- 订单故障 cart 恢复、order=None、compensated=2；
- AR011 30/30；edge 181 passed。
