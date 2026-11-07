# [AR010] 详细设计

## 1. 技能库

```python
search_skill(query)
add_item_skill(pid, qty)
checkout_skill()
```

每个技能是参数化动作模板；元素解析使用当前真实观测的 `accessible_name/role`，执行仍走 `BrowserEnv`。

## 2. 技能执行

```python
async def run_skill(env, steps, task) -> SkillResult:
    obs = await env.observe()
    for step in steps:
        if step.goto: execute(goto)
        else:
            eid = find(obs, step.name, step.role)
            if not eid: return fail
            execute(action with eid)
        obs = await env.observe()
        if not ok: return fail
    return success
```

- 记录 `source=skill`；
- 不调用模型、不产生 token；
- 失败返回当前观测，供回退。

## 3. 技能层级

```
reset(task)
for subtask in decompose(task):
    if run_skill(subtask): continue
    else: LLM rollout(subtask, initial_obs=obs)
final = verifier(original task)
```

- 控制器导航内置在技能首步（goto `/` 或 `/checkout`）；
- 加购技能保留购物车状态。

## 4. 评测

| 条件 | 布局 | churn | 执行 |
|------|------|-------|------|
| baseline | v1 | 否 | LLM 层级 |
| skill | v1 | 否 | 技能优先 |
| skill_churn | v2 | 是 | 技能优先 |

- LLM 调用数 = `source=policy` 的步数；
- prompt/gen tokens 从 StepRecord 统计；
- 成功由原任务验证器判定。

## 5. 回退

- 若 skill 成功率 <100% 或 LLM 调用下降 <50%，保留 baseline，记录负结果；
- 技能失败回退步骤计入 LLM 调用，保证统计真实。

## 6. 风险

| 风险 | 缓解 |
|------|------|
| 技能过拟合 v1 | v2+churn 迁移测试 |
| 元素语义名变化 | 解析失败即回退 |
| 技能掩盖模型能力 | 记录 LLM 调用/回退次数 |
| 技能是硬编码 | 技能来自真实成功轨迹的动作模式，参数化并文档化 |
