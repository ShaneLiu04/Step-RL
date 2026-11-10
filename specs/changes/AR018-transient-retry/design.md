# [AR018] 详细设计

## 1. 服务端

- `LocalShopServer(fault_add_once=True, fault_order_once=True)`；
- 首次 `/add` 或 `/place-order`：设置 `state.flags[...]`，返回 500 错误页；
- 后续请求正常；
- `/api/reset` 清空 flags，重试会话重新计数（但故障已消耗于旧会话，实际重试成功）。

## 2. 运行时

`run_task(..., skill_retries=1)`：

```python
retries_used = 0
for attempt in range(max_attempts):
    rollout = skill_hierarchy(spec)
    if rollout.success: return
    if retries_used < skill_retries:
        retries_used += 1
        continue
    ... replan / fallback ...
```

- 每次 `run_skill_hierarchy` reset 会话；
- 记录 attempt 模式 `retry`。

## 3. 基线

直接 `run_skill_hierarchy` 一次，不重试。

## 4. 评测

3 个任务，fault_add/order 一次性；记录订单、尝试次数、耗时。

## 5. 风险

| 风险 | 缓解 |
|------|------|
| 重试掩盖真实 bug | 只重试一次，记录 attempt |
| 重复下单 | 故障发生在订单创建前，失败无订单 |
| reset 清故障计数 | 重试前故障已消耗；真实 HTTP 500 验证 |
