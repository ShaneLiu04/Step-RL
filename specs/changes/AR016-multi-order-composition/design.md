# [AR016] 详细设计

## 1. 服务端

`SessionState.orders: List[Dict]`：

- `/place-order` 生成订单并 append；
- `order = last` 保持兼容；
- `/order/<id>` 从历史查找；
- snapshot 返回 `orders`；
- reset 清空。

## 2. TaskSpec

```python
order_sequence: List[Dict[str,int]] = []
```

`predicate_names()` 若存在序列，返回 `["orders_sequence_placed"]`。

## 3. 验证器

```python
def orders_sequence_placed(state, url):
    for expected in task.order_sequence:
        if not any(all(order.items.get(pid,0) == qty for ...)):
            return False
    return True
```

使用精确数量；允许历史中还有额外订单（正常）。

## 4. 技能执行

`run_skill_hierarchy(..., reset=True)`：

- 第 1 单 reset；
- 后续 reset=False，直接 observe 当前页；
- 每单技能：add（含 goto `/`）+ checkout（订单后清空）。

## 5. 运行时

```python
async def run_order_sequence(env, task, model, tokenizer):
    for i, targets in enumerate(task.order_sequence):
        sub = TaskSpec(targets=targets, require_checkout=True, level=...)
        rollout = await run_skill_hierarchy(env, sub, ..., reset=(i==0))
        if not rollout.success: return False
    return compute_progress(final, url, task).success
```

## 6. 基线

LLM 层级对合并 targets 的 TaskSpec 执行一次，生成一笔订单；序列验证失败。

## 7. 风险

| 风险 | 缓解 |
|------|------|
| 多订单导致状态污染 | 每单独立 TaskSpec，最终按历史验证 |
| reset 清空历史 | 仅第 1 单 reset，后续不 reset |
| LLM 也拆分订单 | 如实记录，保留效率收益 |
| 购物车未清空 | 服务端订单后清空是真实行为 |
