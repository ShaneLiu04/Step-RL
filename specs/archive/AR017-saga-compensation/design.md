# [AR017] 详细设计

## 1. 服务端

- 订单创建时 `status="active"`；
- `/cancel/<id>`：找到订单，`status="cancelled"`，返回 JSON；
- `/api/state` 的 `orders` 含状态。

## 2. BrowserEnv

```python
async def cancel_order(order_id):
    return await page.evaluate(
        "(id) => fetch('/cancel/' + id).then(r => r.json())", order_id
    )
```

## 3. TaskSpec / 验证器

- `compensate_on_failure: bool`；
- `predicate_names` 在补偿任务返回 `["orders_all_cancelled"]`；
- 验证：历史非空且所有订单 status=cancelled。

## 4. 运行时

```python
placed = []
for order in sequence:
    before = len(orders)
    rollout = run_skill_hierarchy(...)
    if not rollout.success:
        if compensate:
            for oid in placed: await env.cancel_order(oid)
        break
    placed.extend(new_order_ids)
```

- 基线 `compensate=False`；
- Saga `compensate=True`；
- 最终按验证器判定。

## 5. 场景

S1：p3×1 成功；p4×2 因 p4 库存 0 失败；取消 p3 订单。
S2：p2×1 成功；p3×2 因 p3 库存 0 失败；取消 p2 订单。

## 6. 风险

| 风险 | 缓解 |
|------|------|
| 取消接口无真实效果 | 服务端状态真实变更，快照可审计 |
| 第二单未失败 | 服务器 stock_overrides=0，真实加购失败 |
| 基线也取消 | 基线无补偿逻辑，记录订单状态 |
