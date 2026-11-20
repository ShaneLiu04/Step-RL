# [AR027] 购物车事务编译器需求设计说明书

| 字段 | 内容 |
|------|------|
| AR 编号 | AR027 |
| 主题 | cart-transaction-compiler |
| 关联 | EX002 E2/E7（长链路、故障补偿） |
| 日期 | 2026-11-19 |
| 状态 | Draft |

## 1. 背景与目标

EX002 显示：单商品技能与长事务已可用，但“购物车级整体变换”（所有商品加倍/
统一改量/每件加一）没有一等能力。当前 planner 要么返回 None（显式缺口），
要么误解释成单商品加购；技能层也没有跨多商品的事务语义。

目标：新增 **CTC（Cart Transaction Compiler）**——从真实购物车状态解析目标，
逐项执行 `update_quantity`，**每一项都用服务端状态复核**；失败时按原数量
真实回滚，保证不会留下半完成购物车。要求 baseline 0/3、CTC 3/3、0 LLM，
v1/v2 30 场景零回退。

## 2. 范围

**In Scope：**
- `TaskSpec.cart_transform`；
- planner 识别“购物车 + 所有/每件/都 + 加倍/改成N/加N”；
- runtime 事务执行、逐项 verifier 复核、失败补偿；
- 真实 HTTP 故障注入 `fault_update_once/fault_update_pid`；
- 观测去重修复（多行 cart 同 selector 不得丢失）；
- 测试/评测/README/REPRODUCTION/归档/Gitee。

**Out of Scope：** 跨进程事务、分布式锁、LLM 训练、任意自然语言解析。

## 3. 功能需求

### FR1 事务规划
- 仅对“购物车/购物袋 + 全局词（所有/每件/全部/都/各）”生效；
- 提及具体商品时走单商品 AR015 路径，不得误判；
- 支持 `double`、`set:N`、`add:N`；目标超出 1–9 显式失败。

### FR2 事务执行与复核
- 从真实 `/api/state` 读取当前 cart，计算目标；
- 对每项执行 `update_quantity`；每步后用服务端状态复核；
- 全部成功且验证器 cart_contains 通过才 success。

### FR3 失败补偿
- 任一项失败：按执行顺序逆序/顺序恢复已修改项到原数量；
- 每项补偿也用服务端状态复核；
- 返回 `compensated` 计数与显式错误，不伪装成功。

### FR4 观测正确性
- 同一页面多行 cart 的 `<input name="qty">` 可能共享 CSS path；
- 观测必须按 DOM 节点去重，不能按 selector 去重，否则第二行消失。

### FR5 消融
- `run_task(enable_cart_transform=False)` 关闭 CTC，用于真实 baseline；
- 默认开启，其余 30 场景行为不变。

## 4. 非功能需求

| 类型 | 要求 |
|------|------|
| 真实性 | 真实 HTTP/Edge；故障注入是真实 500 响应 |
| 可靠性 | 失败必须回滚到原状态；显式错误 |
| 性能 | 不调用 LLM；动作数/耗时可审计 |
| 兼容 | AR011 30/30、edge 套件零回退 |

## 5. 约束与假设

- 站点数量范围 1–9；超出直接拒绝；
- 当前只支持购物车中已有商品的整体变换；
- 补偿依赖可逆的 update_quantity；
- 事务边界为单会话单次 run_task。

## 6. 验收标准

- 3 个真实任务：baseline 0/3，CTC 3/3，0 LLM；
- 故障任务：success=false、compensated=1、cart 恢复；
- AR011 30/30、0 LLM；edge 175 passed。
