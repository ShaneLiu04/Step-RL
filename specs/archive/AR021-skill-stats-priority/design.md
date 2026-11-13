# [AR021] 增量实现设计

## 1. 总体思路

技能库从「单槽、无记忆」升级为「多候选 + 真实成败统计 + 成功率优先级 +
淘汰让位」。核心不变式：**统计只记录验证器确认的成败**（模型与技能都
不得自述成功），**淘汰只影响选择、不删除注册表**（审计可追溯），
**单候选路径逐字段兼容**（存量技能与旧产物零迁移）。

```
执行子任务
  └─ skill_for_subtask：跳过 demoted → 按 (-success_rate, 注册序) 选候选
  └─ run_skill：真实 DOM 执行（语义元素）
  └─ compute_progress(子任务) ── 验证器确认 ok / fail
       └─ skill_stats.record(name, ok, note)   ← 唯一记录点
            └─ 策略：attempts≥1 且 rate<0.5 → demoted（让位/回退）
```

## 2. 模块改动

### 2.1 `step_rl/edge/skill_stats.py`（新模块）

无 edge 内部依赖（纯数据 + 策略），避免导入环。

```python
DEMOTION_MIN_ATTEMPTS = 1
DEMOTION_MAX_RATE = 0.5          # 严格小于才淘汰

@dataclass
class SkillStat:
    name: str
    operation: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    last_success_at: str = ""    # ISO8601
    last_failure_at: str = ""
    last_failure_note: str = ""
    demoted: bool = False
    demotion_reason: str = ""

    @property
    def success_rate(self) -> float: ...

def record_skill_outcome(name, operation, success, note="") -> SkillStat
def get_skill_stat(name) -> Optional[SkillStat]
def all_skill_stats() -> Dict[str, SkillStat]
def is_demoted(name) -> bool
def clear_skill_stats() -> None
def reset_skill_stats(name) -> None          # 同名再注册时用
def save_skill_stats(path) -> None          # 审计 JSON（含 policy）
def load_skill_stats(path) -> List[str]
def to_dict() / from_dict()                  # JSON 形状
```

记录语义：`record_skill_outcome` 幂等无副作用（只改内存）；淘汰判定在
记录后即时执行；`demoted` 一旦置位不被后续成功自动撤销（撤销只能经
「同名再注册 → 统计重置」或显式 `reset_skill_stats`），避免振荡。

### 2.2 `skill_library.py`（向后兼容升级）

- `_INDUCED: Dict[str, List[Dict[str, Any]]]`：每个候选
  `{"name", "steps", "order", "registered_at"}`；`order` 为进程内单调
  注册序号（选择 tie-break 与审计用）。
- `register_induced_skill(operation, template, name="")`：
  1. 同名候选已存在 → 替换 `steps`、更新 `registered_at`、
     `reset_skill_stats(name)`（新轨迹 = 新证据）；
  2. 否则 append（新 `order`）。
- `_select_best(candidates)`：
  ```
  eligible = [c for c in candidates if not skill_stats.is_demoted(c.name)]
  pool = eligible or candidates          # 全被淘汰时退回全量（只读展示）
  return min(pool, key=lambda c: (-rate(c.name), c["order"]))
  ```
  未测试 `rate = 0.0`。单候选时恒返回该候选 → 与旧版行为一致。
- `skill_for_subtask`：induced 分支改为 `_materialize(_select_best(...), task)`；
  其余分支（search/add/checkout/update/显式缺口 None）逐字不动。
- `run_skill_hierarchy`：技能执行、验证器确认 `ok` 之后
  `record_skill_outcome(skill.name, subtask.operation, ok, note)`；
  `ok` 的计算、回退（fallback LLM rollout）与 Rollout 组装不变。
- `save_induced_skills`：每 operation 写 `_select_best` 结果
  `{"name", "steps"}`（单候选 = 旧形状逐字段一致）；全部候选被淘汰的
  operation 从文件省略（诚实表达「该操作无可用技能」）。
- `load_induced_skills`：读旧格式文件 → 逐条 `register_induced_skill`
  （每 operation 一条候选），返回 operation 列表，API 不变。
- `induced_operations()` 不变（按 operation 排序）。

### 2.3 `capability.py`

不改代码：`check_capability` 经 `skill_for_subtask` 选择候选，全部候选
淘汰时自然得到 `no_skill_for_level_{level}` 显式缺口（AR019 语义）。

### 2.4 `scripts/ar021_baseline_probe.py`（改动前执行，旧代码留证）

探针（全部真实执行，旧代码）：

- A 单槽覆盖：`remove` 先注册模板 X（名 `tpl_x`）再注册模板 Y（名
  `tpl_y`）→ `skill_for_subtask` 物化的是 Y（X 被静默覆盖）；且旧代码
  无统计 API（`hasattr(skill_library, "all_skill_stats") == False`）；
- B 无记忆重选：注册失效 remove 技能（`click button "删除 {product}"`，
  真实站点按钮为「移除 …」，`_find` 必然 `element not found`）；两个
  全新服务端会话各真实执行一次单商品移除（v1，seed p3×2）：两次都失败、
  购物车仍含 p3、选中技能名相同；第一次失败后门控仍 `covered`
  （技能仍在注册表）——失败无状态、无让位。

输出 `outputs/ar021/baseline_probe.json` + `baseline_probe.md`。

### 2.5 `scripts/ar021_eval.py`（改动后主评测）

结构对齐 AR019/AR020：`set_seed(42)`；P0–P5；每阶段 JSON 落盘
`outputs/ar021/eval/ar021_results.json` + `ar021_report.md` +
`induced_skills.json` + `skill_stats.json`（审计）。

- P0 复核：真实规划器 + 注册表：异名两候选并存（`induced_candidates`
  可见）、选择规则（先注册未测试者优先）、统计 API 存在；
- P1 注入失败：仅注册失效候选 `induced_remove_stale`（步骤
  `goto /cart` + `click button "删除 {product}"`）；真实执行
  `把购物车中的无线充电器移除`（v1，seed p3×2，组合运行时
  `runtime.run_task`）：
  - attempts[0] 技能模式失败（真实 DOM miss）→ 统计 0/1 → `demoted`；
  - 门控翻转：`no_skill_for_level_2`（显式缺口，留证）；
  - `run_task` 内部真实 LLM 兜底（GPU，AR004 适配器）完成任务，
    最终 `success=True, fallback=True`，`env.get_state()` cart 为空；
- P2 干净重归纳：`clear_induced_skills()` → 门控缺口复核 → 真实 LLM
  兜底（`TrajectoryRecorder` + `run_hierarchy`，GPU）→ `induce_skill`
  → 注册 `induced_remove`（好技能）→ 持久化 induced_skills.json；
- P3 让位：注册表内同时存在「已淘汰的 stale」与「新归纳的好技能」，
  同一指令技能路径复跑（不加载模型）：成功、0 LLM；审计
  `stale.attempts == 1`（未被再次选中）且 `induced_remove.attempts == 1`；
- P4 迁移：p4 单商品 v1 + p3 v2 全量 ID churn，技能路径 0 LLM；
- P5 门禁：
  - `C:\Python311\python.exe -m pytest tests -q --tb=no --ignore=tests/test_locator.py --ignore=tests/test_progress_estimator.py --ignore=tests/test_smart_wait.py`
    （期望全过：166 基线 + 本 AR 新增）；
  - `C:\Python311\python.exe scripts/ar011_eval.py`（30 场景，须 30/30、
    0 LLM，summary JSON 校验 `success_rate==1.0` 与 `policy_steps==0`）。

决策：P1–P4 全成功 + 门禁全过 → `keep`；任一失败 → `rollback`
（负结果归档，不删产物）。

## 3. 关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| D1 | 成败判据 = 子任务验证器 `compute_progress(...).success`，不是 `SkillResult.ok` 的逐步执行结果，也不是模型自述 | 与 AR001 验证红线一致：成功必须外部可执行确认；技能最后一步执行「看似成功」但服务端状态不对时不得计成功 |
| D2 | 淘汰策略 `attempts≥1 且 rate<0.5`（严格小于） | BACKLOG 验收「注入一次失败技能后统计下降并让位」要求单次失败（0/1=0）即让位；1/2=0.5 不淘汰避免瞬态故障（AR018 场景）直接打死技能 |
| D3 | 淘汰只移出选择集，不删注册表、不删审计 | 可追溯、可人工 `reset_skill_stats` 恢复；与「不删除过程产物」纪律一致 |
| D4 | 同名再注册 = 替换步骤 + 统计重置 | 重新归纳的轨迹是新证据；避免旧失败记录永久压制新模板（闭环自愈） |
| D5 | 未测试候选 rate=0.0，同率先注册优先 | 单候选/存量场景行为与旧版一致；已测试未淘汰者恒 ≥0.5，被证明的技能自然优先 |
| D6 | 记录钩子只放 `run_skill_hierarchy`（统一真实执行路径） | AR011 30 场景、多订单、Saga 等全部经此路径，一处记录全链路可见；不碰 runtime/planner |
| D7 | `save_induced_skills` 保持旧 JSON 形状（写被选中候选） | AR019/AR020 产物与 `load_induced_skills` 零迁移 |

## 4. 测试设计（`tests/test_edge_skill_stats.py`）

纯逻辑（无浏览器）：

1. 策略：0/1 → demoted；1/1 → 保留；1/2（0.5）→ 保留；再失败 1/3 → demoted；
2. 连续失败计数与 last_* 时间戳/note 记录；
3. save/load 往返（tmp_path）：淘汰状态、policy 常量一致；
4. 多候选选择：双未测试候选 → 先注册者；对先注册者记失败淘汰后 → 选中切换到后注册者（让位）；
5. 已证明（1/1）候选优先于未测试候选；
6. 同名再注册重置统计（demoted → 未淘汰，attempts 归零）；
7. `save_induced_skills` 单候选 JSON 形状 == 旧格式（逐字段）；
8. `load_induced_skills` 读 AR019 产物形状文件 → 物化正确。

真实浏览器（`pytest.importorskip("playwright")`，模式同既有测试）：

9. 真实 remove 技能执行成功 → 统计 1/1、`demoted=False`；
10. 真实注入失效技能 → 两次真实执行：第一次失败且被淘汰；再注册好技能
    后第二次执行成功且失效技能 attempts 冻结在 1（让位）。

既有约束：AR019/AR020 全部测试不回退（11 + 12 项）。

## 5. 风险与对策

| 风险 | 对策 |
|------|------|
| 记录钩子改变 AR011 行为 | 钩子只写内存字典；P5 门禁 30/30 + 0 LLM 校验 |
| 单失败淘汰过激（瞬态 500） | AR018 重试在执行内消化；被误淘汰后经 D4 闭环自愈（重新归纳重置）；负结果如实记录 |
| 注册表形状变化破坏旧测试 | 单候选路径逐字段兼容 + 既有测试全绿为硬门禁 |
| LLM 兜底（P1/P2）GPU 失败 | 诚实负结果：记录 rollback，不伪造归纳 |
| 选择 tie-break 不确定性 | 注册序号（进程内单调）保证确定性；审计文件可复查 |

## 6. 回滚

- 代码：`git revert` 本 AR 提交（`skill_stats.py` 删除 + `skill_library.py`
  恢复 + 评测/测试移除）；
- 运行态：`clear_induced_skills()` + `clear_skill_stats()`；
- 已归档产物不动。

## 9.1 组合回退规则（沿用 AR001 design §9.1）

以 **A = 当前最优（AR020 状态：edge 166 passed；AR011 30/30、0 LLM；
AR020 批量 3/3 + 单商品 3/3、0 LLM、约 10.5×）** 为初始最优。

1. B = A + 统计/选择/淘汰（无淘汰发生路径）：B 的 30 场景与 edge 套件
   必须 ≥ A（30/30、0 LLM、全过），否则回退 A；
2. C = A + 淘汰让位（P1/P3 真实注入失败链路）：C 在 B 基础上须真实
   达成「失败留痕 → 统计下降 → 让位 → 0-LLM 复用」，且 B 的全部门禁
   不回退，否则回退 B 并记录负结果；
3. 任何回退都写入 `ar021_report.md` 与 BACKLOG，不删除失败实验；
4. 全过 → 组合最优前移，README 版本递增。
