# [AR020] 增量实现设计

## 1. 总体思路

```
"把 A 和 B 从购物车移除" ──planner(批量解析, FR1)──▶ TaskSpec(targets={a:0, b:0})
        │
   能力门控（逻辑不变）
        │  skill_for_subtask: operation=remove ∈ _INDUCED → 命中
        ▼
   _materialize（多目标展开, FR2）
        │  prefix 一次 + unit×N（按 targets 插入序）+ suffix 一次
        ▼
   run_skill_hierarchy（0 LLM）
        │
        ▼
   验证器 cart_without（多目标，不改）→ 全部 targets 数量为 0
```

模板本体仍是**单商品单元**（AR019 语义）；批量是运行时的循环展开，
不写进模板。P1 的 LLM 批量兜底轨迹经 `induce_skill` 归纳时由
`collapse_repeated_product_steps`（FR3）折回单商品单元，注册物与
AR019 模板同构。

## 2. 模块改动

### 2.1 planner.py（remove 分支，向后兼容）

```python
if any(word in instruction for word in ("移除", "删除")) and mentions:
    first = by_pid[mentions[0][0]]
    return TaskSpec(
        task_id="planned_remove",
        level=2,
        goal=instruction,
        search_query=first.keywords[0] if first.keywords else first.name,
        targets={pid: 0 for pid, _ in mentions},          # 全部提及商品
        require_checkout=False,
        operation="remove",
        predicates=["cart_without"],
        start_path="/cart",
        seed_cart={pid: max(qty, 1) for pid, qty in mentions},
    )
```

单商品指令：`mentions` 长度为 1，targets/seed_cart 与旧版逐键相同。

### 2.2 skill_library.py `_materialize`（多目标展开）

```python
def _split_product_unit(steps):
    """(prefix, unit, suffix)：unit 为从首个 {product} 步骤起的连续段。"""
    has = lambda s: "{product}" in str(s.get("name", "")) or \
                       "{product}" in str(s.get("value", ""))
    idx = next((i for i, s in enumerate(steps) if has(s)), None)
    if idx is None:
        return list(steps), [], []
    end = idx
    while end < len(steps) and has(steps[end]):
        end += 1
    return steps[:idx], steps[idx:end], steps[end:]

def _materialize(entry, task):
    pids = list(task.targets)
    prefix, unit, suffix = _split_product_unit(entry.get("steps", []))
    steps = []
    for item in prefix:
        steps.append(_inst(item, pids[0]))
    for pid in pids:
        for item in unit:
            steps.append(_inst(item, pid))
    for item in suffix:
        steps.append(_inst(item, pids[0]))
    ...
```

- `_inst(item, pid)`：`{product}` → 商品名、`{qty}` → 该 pid 的目标数量
  （remove 任务为 "0"），与旧实现同一替换顺序；
- **单目标证明**：`pids=[p]` 时 prefix+unit×1+suffix 的替换对象与旧版
  （始终取第一个 pid）相同 → 逐步一致；
- 无 `{product}` 步骤的模板（如纯 checkout）：unit 为空，输出=原序列。

### 2.3 skill_induction.py（归纳规范化）

- `induce_skill`（AR019，单商品路径）：输出逐字段保持不变；接入共享
  `_generalise_record` 与 `collapse_repeated_product_steps`（单商品轨迹
  无连续同形步，折叠为 no-op）。
- `induce_batch_template(task, records, catalog)`（AR020 批量路径）：
  1. 按真实「移除 <商品名>」点击把轨迹切分为**逐商品块**（块核 = 首个
     引用商品的记录 → 该商品移除点击）；引用商品的记录之前、不引用商品
     的记录为**前缀**（如 LLM 的游离 type）；
  2. 每块泛化（商品名 → `{product}`，目标数量 → `{qty}`）；
  3. **unit = 泛化块的"最长公共后缀"**：兜底 LLM 不可精确重复（真实 P1
     轨迹对 p3 做 `更新数量→移除`、对 p2 只做 `移除`，块是前缀单调而非
     严格相等），公共后缀是"对每件商品都被证明能完成移除"的最小模式；
     成功轨迹每块必以各自 `移除 {product}` 收尾 → 后缀非空且以
     `移除 {product}` 收尾；
  4. 块数 <2 或公共后缀为空 → 返回 `None`（显式能力缺口，防御性不变量，
     永不伪造模板）；
  5. 模板 = 泛化前缀 + unit，经 `register_induced_skill` 注册、
     `_materialize` 多目标展开（§2.2）。

### 2.4 scripts/ar020_baseline_probe.py（改动前执行）

- 探针 A（规划）：真实 server + `fetch_catalog`，规划批量指令
  「把无线充电器和蓝牙降噪耳机从购物车移除」→ 记录 `spec.targets`
  （旧代码预期 `{"p3": 0}`，p4 丢失）；
- 探针 B（实例化）：加载真实持久化模板
  `outputs/ar019/eval/induced_skills.json`（AR019 产物，不重造），
  手工构造批量 TaskSpec `{p3:0, p4:0}`（seed 2/3），真实 Edge 跑
  `run_skill_hierarchy` → 记录最终 cart（旧代码预期仍含 p4、验证判负）；
- 探针 C（单商品对照）：同模板单商品 p3 任务 → 预期成功（证明环境/模板
  本身可用，缺陷只出在批量链路上）；
- 产物 `outputs/ar020/baseline_probe.json` + `baseline_probe.md`；
  探针脚本与产物在**改动前**提交，锁定 before 证据。

### 2.5 scripts/ar020_eval.py（改动后主评测）

P0（改动后复核，同探针 A 指令）→ P1 真实 LLM 兜底（`load_multi_adapter`
+ AR004 三适配器，seed=42，`TrajectoryRecorder` 包装 `BrowserEnv`，
`max_steps_per_subtask=14`）→ P2 归纳/注册/持久化 + 门控翻转 →
P3 批量复跑 ×3 → P4 单商品回归 ×3 → P5 组合门禁（subprocess：
`C:\Python311\python.exe -m pytest tests -q --tb=no`（忽略 legacy 三文件）
+ `python scripts/ar011_eval.py`）。

任务集（指令 → 规划器 → TaskSpec，全部真实 catalog 解析）：

| 编号 | 指令 | targets | seed | 布局 |
|------|------|---------|------|------|
| P1 | 把两个无线充电器和三条USB-C 快充数据线从购物车移除 | {p3:0, p2:0} | {p3:2, p2:3} | v1 |
| B1 | 把无线充电器和蓝牙降噪耳机从购物车移除 | {p3:0, p4:0} | {p3:1, p4:1} | v1 |
| B2 | 把两个无线充电器和三条USB-C 快充数据线从购物车移除 | {p3:0, p2:0} | {p3:2, p2:3} | v1 |
| B3 | 把蓝牙降噪耳机和USB-C 快充数据线从购物车移除 | {p4:0, p2:0} | {p4:1, p2:1} | v2, churn=1.0 |
| S1 | 把购物车中的无线充电器移除 | {p3:0} | {p3:1} | v1 |
| S2 | 把购物车中的蓝牙降噪耳机移除 | {p4:0} | {p4:1} | v1 |
| S3 | 把购物车中的无线充电器移除 | {p3:0} | {p3:1} | v2, churn=1.0 |

产物：`outputs/ar020/eval/{ar020_results.json, ar020_report.md,
induced_skills.json}`。

## 3. 关键设计决策

| 决策 | 理由 |
|------|------|
| 模板保持单商品单元，批量在运行时展开 | 模板必须忠实自真实轨迹；轨迹里"每件商品移除一次"是单元，批量是该单元的循环。若把 N 个商品的步写进模板，模板与"商品"的对应关系会随 N 漂移，单商品路径被破坏 |
| prefix/unit/suffix 三段切分 | 非商品步骤（如 goto）只执行一次；每商品单元逐目标展开；后缀一次。无 `{product}` 的模板退化为原序列 |
| unit 取泛化块的最长公共后缀 | 真实 P1 轨迹证明兜底 LLM 块是前缀单调而非严格相等（p3 多做了 `更新数量`）；公共后缀是"对每件商品都被证明有效"的最小模式，天然以 `移除 {product}` 收尾，单商品路径（AR019）不受影响 |
| before 证据用改动前提交锁死 | 探针在旧代码上执行并提交，杜绝"事后解释基线" |
| 批量执行顺序取 targets 插入序 | 验证器 `cart_without` 与顺序无关；插入序=指令文本序，可审计 |

## 4. 测试设计

`tests/test_edge_batch_remove.py`（真实本地 server；浏览器项
`importorskip("playwright")`，沿用 AR019 风格）：

1. 规划器：批量指令 → `targets` 含全部提及商品（真实 catalog）；
2. 规划器：单商品指令 → 与旧行为一致（`targets=={"p3": 0}`、
   `seed_cart=={"p3": 1}`）；
3. 归纳：两次「移除」点击轨迹 → 模板 = 前缀 goto + 单个 `移除 {product}`
   单元；
4. 归纳：AR019 形状轨迹（游离 type + 数量 + 更新 + 移除，两商品同形）
   → 4 步模板（前缀 1 + 单元 3）；
5. 归纳：**真实 P1 形状**（游离 type + p3[更新,移除] + p2[移除]，前缀单调
   块）→ unit = 最长公共后缀 `[移除 {product}]`，模板 2 步；
6. 归纳：不同长块（p3[数量,更新,移除] vs p4[数量,移除]）→ unit 仅
   `[移除 {product}]`；
7. 归纳：单目标任务 → `None`（批量路径不适用于单商品）；
8. 归纳：单商品轨迹经 `induce_skill` → 折叠 no-op（AR019 兼容证明）；
9. 实例化：AR019 真实 4 步模板 + 双目标 → 前缀 1 + 单元 3×2 + 后缀 0，
   点击步商品名按 targets 序排列；
10. 实例化：单目标 → 步骤数与逐字段与旧算法一致；
11. `skill_for_subtask`：批量任务命中诱导技能（非 None）；
12. 验证器：`cart_without` 双目标语义（空车真 / 剩一件假）；
13. 真实浏览器：批量任务注册模板后 `run_skill_hierarchy` 成功、cart 为空。

## 5. 风险与对策

| 风险 | 对策 |
|------|------|
| AR019 真实模板含冗余数量步（type "2"、设数量、更新） | 对 `cart_without` 验证无害；P1/P3 用真实执行验证，如出现副作用如实记录 |
| LLM 兜底批量顺序/步数超 14 | 如实记录负结果按 §9.1 回退，不伪造归纳 |
| v2 churn 下元素重编号 | 移除按钮以 aria-label 语义名定位，churn 只改 eid（AR019 P4b 已验证同机制） |
| 探针与主评测并发端口 | 每个阶段自启 server（port 0 动态分配），串行执行，不并发 |
| `_materialize` 兼容破坏 AR019 产物 | 单目标 bit 级一致（§2.2 证明 + 单测 5/6 双保险） |

## 6. 回滚

全部改动为新增（planner 分支替换、`_materialize` 重写、归纳侧新函数、
两个脚本、一个测试文件）；单测覆盖；`git revert` 到 AR019 状态即可。

## 9.1 组合回退规则（沿用 AR001 design §9.1）

- 新组合（AR020 + 全部既有 AR）必须在 edge 套件（≥153 passed）与
  AR011 30 场景（30/30、0 LLM）上不低于现状方可保留；
- 任一门禁失败：回退到上一最优组合，并在 README「组合回退记录」中
  登记负结果与原因。
