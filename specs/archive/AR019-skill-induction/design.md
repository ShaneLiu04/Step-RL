# [AR019] 增量实现设计

## 1. 总体思路

```
指令 ──planner──▶ TaskSpec(operation=remove)
        │
        ▼
   能力门控 check_capability
        │  skill_for_subtask → None（未注册）
        ▼ covered=False        【P0 缺口证据】
   LLM 兜底 run_hierarchy ──TrajectoryRecorder──▶ RecordedStep[]
        │  真实 GPU 推理 + 真实浏览器执行        【P1】
        ▼ 成功
   induce_skill ──泛化──▶ template[{product}/{qty}]
        │                                    【P2】
        ▼ register + persist(JSON)
   skill_for_subtask → materialize(task)
        │
        ▼
   run_skill_hierarchy（0 LLM）              【P3/P4 复用与迁移】
```

## 2. 模块改动

### 2.1 site.py

- `do_GET` 新增 `/remove/{pid}`：`state.cart.pop(pid, None)` → 302 `/cart`；
  非法 pid → 400 错误页。
- `render_cart` / `_render_v2_cart`：每行追加
  `<form action='/remove/{pid}' method='get'>` +
  `<button aria-label='移除 {p.name}'>移除</button>`。

### 2.2 verifier.py

- 新谓词 `cart_without`：目标商品购物车数量全为 0（含不存在）。

### 2.3 planner.py

- 触发词表追加「移除」「删除」；
- `plan_instruction` 在 update 分支后新增 remove 分支：
  `targets={pid: 0}`、`operation="remove"`、`predicates=["cart_without"]`、
  `start_path="/cart"`、`seed_cart={pid: max(qty,1)}`。

### 2.4 skill_library.py（新能力，兼容旧行为）

```python
_INDUCED: Dict[str, Dict[str, Any]] = {}   # operation -> {name, steps}

register_induced_skill(operation, template, name="")
clear_induced_skills()
induced_operations() -> List[str]
save_induced_skills(path) / load_induced_skills(path) -> List[str]
_materialize(entry, task) -> Skill        # {product}/{qty} 占位替换
```

- `skill_for_subtask` 顺序：update 分支（不变）→ 诱导注册表 →
  **非 add 操作返回 None**（新守卫，防止 remove 误路由 add 技能）→
  原有 level 路由。
- 既有任务 operation 均为默认 `"add"`，零影响。

### 2.5 skill_induction.py（新文件）

```python
@dataclass RecordedStep: kind/url/role/name/value

class TrajectoryRecorder:
    # 包装真实 BrowserEnv；observe() 缓存 eid→元素元数据；
    # execute() 真实执行并记录 (kind, role, accessible_name, text, url)
    # 其余属性 __getattr__ 透传

def induce_skill(task, records, catalog) -> Dict[str, Any]:
    # goto → 保留 url；click/type → role+name(+value)
    # 商品名 → {product}；纯数字且∈targets 值 → {qty}
```

### 2.6 scripts/ar019_eval.py

P0 门控缺口 → P1 LLM 兜底（`load_multi_adapter` + AR004 适配器，
seed=42）→ P2 归纳持久化 → P3 技能复跑 → P4 迁移（p4/v1、p3/v2+churn）
→ P5 组合门禁（subprocess：pytest 全量 + ar011_eval）。
产物：`outputs/ar019/eval/{ar019_results.json, ar019_report.md,
induced_skills.json}`。

## 3. 关键设计决策

| 决策 | 理由 |
|------|------|
| 记录在执行前解析元素元数据 | 观察快照后 ID 扰动/页面变化不会丢失语义信息 |
| 模板保留完整成功轨迹 | 轨迹成功即最小可复现单元；不做启发式裁剪 |
| 占位符只用 `{product}/{qty}` | 与技能步 `name/role/value` 结构正交，可 JSON 持久化 |
| 注册表模块级 + 显式 clear | 单测可重置；运行时注册一次全局生效 |
| 未注册非 add → None | 能力缺口必须显式，不得静默误路由 |

## 4. 测试设计

- `tests/test_edge_skill_induction.py`：
  - `/remove` 路由（真实 HTTP）；
  - `cart_without` 谓词真/假例；
  - 规划器 remove 指令解析（真实 catalog）；
  - 归纳前 `skill_for_subtask` 为 None + 能力门控未覆盖；
  - `induce_skill` 泛化（`{product}`/`{qty}`）；
  - 注册/持久化 roundtrip；
  - 真实浏览器技能复跑（注册模板 → 移除成功、购物车为空）。

## 5. 风险与对策

| 风险 | 对策 |
|------|------|
| LLM 兜底失败 | 如实记录负结果，按 §9.1 回退；不伪造归纳 |
| 模板含冗余步 | 成功轨迹原样回放仍成功；冗余只影响步数不影响正确性 |
| 注册表污染既有评测 | 每次测试/评测前 `clear_induced_skills()`；注册键仅 `remove` |

## 6. 回滚

全部改动为新增（一个新文件 + 各模块小增量），单测覆盖；`git revert`
单提交即可恢复 AR018 状态。

## 9.1 组合回退规则（沿用 AR001 design §9.1）

- 新组合（AR019 + 全部既有 AR）必须在 30 场景统一套件上 ≥ 现状
  （30/30、0 LLM）方可保留；
- 任一门禁失败：回退到上一最优组合，并在 README「组合回退记录」中
  登记负结果与原因。
