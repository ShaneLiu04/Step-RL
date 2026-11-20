# [AR027] 增量实现设计

## 1. 总体思路

把“购物车整体变换”从单商品技能的组合提升为一等事务：

1. planner 识别全局 cart 指令 → `TaskSpec(cart_transform=...)`；
2. runtime 读真实 cart，解析目标；
3. 逐项调用 `update_quantity`，每步用服务端状态复核；
4. 任一项失败 → 对已修改项执行原数量补偿并复核；
5. 最终用验证器 `cart_contains` 判定成功。

同时修复观测按 selector 去重导致多行 cart 输入丢失的问题。

## 2. 模块改动

### 2.1 `tasks.py`
- 新增 `cart_transform: str = ""`，追加在末尾保持位置兼容；
- `predicate_names`: 有 transform 时使用 `cart_contains`。

### 2.2 `planner.py`
- `_parse_cart_transform`：要求购物车/购物袋 + 全局词；具体商品提及则放弃；
- 支持 `double`、`set:N`、`add:N`；
- `plan_instruction(..., enable_cart_transform=True)` 早返回 transform spec；
- 默认开启；`False` 用于 baseline 消融。

### 2.3 `runtime.py`
- `_transform_targets(cart, expr)`：解析目标，检查空 cart 与 1–9 范围；
- `run_cart_transform`：逐项执行 + 状态复核 + 失败补偿；
- `run_task(..., enable_cart_transform=True)`：先解析 transform 目标再执行；
- 返回 `attempts[].mode="cart_transform"`、`compensated`、`transform` 审计字段。

### 2.4 `site.py`
- 新增真实故障注入 `fault_update_once` + `fault_update_pid`；
- `/update/` 命中时返回 500，用于验证补偿路径（不是 mock）。

### 2.5 `browser.py`
- 观测去重从 selector 改为 DOM 节点；多行 cart 同一 `input[name=qty]`
  不再丢第二行。

## 3. 关键决策

- **D1 全局意图 vs 单商品**：提及具体商品时绝不走 CTC，避免把 AR015 误吞。
- **D2 每步状态复核**：click 成功不等于服务端更新成功（故障注入会返回 500）；
  必须以 `/api/state` 为准，否则会“假成功”。
- **D3 补偿也复核**：补偿不是再点一次就完事，必须验证恢复后的数量。
- **D4 事务边界显式**：越界/空 cart 直接失败，不部分执行。
- **D5 观测按节点去重**：CSS path 相同的多行控件必须都保留。

## 4. 测试设计

1. planner 解析 double/set/add，并拒绝具体商品改量；
2. 真实 Edge double: {p3:1,p4:2} → {p3:2,p4:4}；
3. 真实 Edge set3: {p3:2,p2:1} → {p3:3,p2:3}；
4. 真实 Edge add1: {p3:1,p4:1} → {p3:2,p4:2}；
5. baseline（enable=False）显式缺口且 cart 不变；
6. 真实故障注入 p4 更新失败 → p3 回滚，cart 恢复，compensated=1。

## 5. 风险与对策

| 风险 | 对策 |
|------|------|
| 具体商品指令被误判为全局 | `_mentions` 非空直接放弃 CTC |
| click 成功但服务端 500 | 每步 `/api/state` 复核 + 故障测试 |
| 补偿后仍不一致 | 补偿也复核，返回 compensated 计数 |
| 多行同一 selector 丢元素 | 观测按 DOM 节点去重 |
| 30 场景回退 | AR011 30/30 + edge 175 门禁 |

## 6. 回滚

回退 AR027 提交：移除 cart_transform/CTC/故障注入/观测去重修复，恢复旧 planner；
AR027 产物保留在 `outputs/ar027/`。

## 7. 组合回退规则

A = 当前最优 AR026（AR011 30/30、0 LLM；edge 169 passed）。
1. B = A + AR027；edge 不得新增失败。
2. B 的 AR011 必须 30/30、0 LLM。
3. B 的 CTC 必须 3/3、0 LLM；故障补偿必须成功。
4. 全部满足 → 保留（v4.16）；否则回退并归档负结果。
