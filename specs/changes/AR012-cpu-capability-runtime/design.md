# [AR012] 详细设计

## 1. 能力门控

```python
def capability(instruction, catalog) -> Capability:
    spec = plan_instruction(instruction, catalog)
    if spec is None: return unsupported
    for subtask in decompose_task(spec):
        if skill_for_subtask(subtask) is None:
            return fallback_required
    return covered
```

## 2. CPU-first runtime

`run_task(env, instruction, model=None)`：

- 技能成功 → 返回；
- 技能失败且 `model is None` → 返回 `fallback_required=True`，不崩溃；
- 有模型时按 AR011 回退。

## 3. 并发

每个会话独立 `LocalShopServer + BrowserEnv`；`asyncio.gather` 执行 N 个任务。记录串行/并行 wall time。

## 4. 评测

| 组 | 条件 | 指标 |
|----|------|------|
| 30 场景 | model=None | 成功、耗时、GPU 占用 |
| 12 任务 | 串行 | wall time |
| 12 任务 | 4 并发 | wall time、成功 |
| 未覆盖 | model=None | unsupported、无异常 |

## 5. 风险

| 风险 | 缓解 |
|------|------|
| 并发浏览器资源竞争 | 限制 4 路，记录失败 |
| 技能误覆盖 | 能力清单显式检查 |
| 无模型回退崩溃 | 显式 fallback_required |
| 并发不稳定 | 每任务独立 server/env |

## 6. 文件

```
step_rl/edge/capability.py   # 覆盖检测
step_rl/edge/runtime.py      # model=None 门控
scripts/ar012_cpu.py         # 30 场景 + 并发
tests/test_edge_capability.py
```
