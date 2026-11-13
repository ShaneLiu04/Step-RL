# [AR021] 需求设计说明书

## 1. 背景与目标

AR019/AR020 建立了「LLM 兜底成功 → 轨迹归纳 → 参数化技能 → 0-LLM 复用」的
能力闭环，但技能库是**无记忆的单槽注册表**：每个 operation 只保留一个模板，
技能执行的成功/失败不留任何统计。这造成两个真实缺陷（改动前基线探针
`scripts/ar021_baseline_probe.py` 留证，`outputs/ar021/baseline_probe.json`）：

1. **单槽覆盖**：同一 operation 再注册一个模板会静默覆盖旧模板，无法并存
   不同来源（不同轨迹/不同布局世代）的候选；
2. **无记忆重选**：注入一个已失效的 remove 技能（站点世代漂移，按钮文案
   「删除」→「移除」）后，连续两次真实执行都选中同一失效技能并失败，
   第二次执行与第一次完全相同——失败没有留下任何状态；能力门控仍报
   `covered`，运行时持续押注一个反复失败的技能，既不让位给更好的候选，
   也不回退到显式缺口（LLM 兜底 + 重新归纳）。

目标（BACKLOG B02）：技能库按**真实执行成功率**统计、排序与淘汰——
失效技能统计下降并让位；成功技能被优先选中；30 场景统一套件不回退。

## 2. 范围

- 新增 `step_rl/edge/skill_stats.py`：技能成败统计、优先级、淘汰策略与
  审计持久化（新模块，不改动旧模块行为）。
- `step_rl/edge/skill_library.py`：单槽 `_INDUCED` 升级为**每 operation
  多候选**注册表；`skill_for_subtask` 按成功率选择；`run_skill_hierarchy`
  在执行后记录**验证器确认**的技能成败。
- 评测 `scripts/ar021_eval.py`（真实 Edge / GPU / 服务端状态）与改动前
  基线探针 `scripts/ar021_baseline_probe.py`（改动前在旧代码上执行）。
- 单测 `tests/test_edge_skill_stats.py`。
- 不在范围：v3 布局（B06）、并发隔离（B07）、观测缓存（B08）、新技能
  类型（B04）、新约束类型（B05）；不训练新模型；不修改 AR001–AR020 已
  归档内容。

## 3. 功能需求

### FR1 技能成败统计（`skill_stats.py`）

- 按技能名（候选模板名）记录：`attempts / successes / failures /
  success_rate / consecutive_failures / last_success_at / last_failure_at /
  last_failure_note / demoted / demotion_reason`；
- 成功/失败判据来自**验证器**（`run_skill_hierarchy` 中子任务执行后的
  `compute_progress(...).success`），不得由技能或模型自述；
- 策略常量：`DEMOTION_MIN_ATTEMPTS = 1`、`DEMOTION_MAX_RATE = 0.5`——
  达到最少次数且成功率**严格低于** 0.5 时淘汰（`demoted=True` 并记录原因）；
  成功率恰好 0.5（如 1/2）不淘汰；
- 审计持久化：`save_skill_stats(path)` / `load_skill_stats(path)` JSON 往返
  （含策略常量），文件可人工审计。

### FR2 多候选注册与优先级选择（`skill_library.py`）

- `register_induced_skill(operation, template, name)` 升级为**按名 upsert**：
  同名再注册 = 替换步骤 + 重置该技能统计（新轨迹是新证据）；异名并存为
  同 operation 的多个候选，保留注册顺序；
- 选择规则（`skill_for_subtask`）：**跳过已淘汰候选** → 剩余按
  `success_rate` 降序、同率按注册顺序（先注册优先）取第一个；
  未测试候选成功率记 0.0（已测试且未淘汰者恒 ≥ 0.5，故被证明的技能
  优先于未测试的）；
- 单候选场景行为与旧版逐字段一致（存量技能零迁移成本）；
- `save_induced_skills` 每 operation 只写**被选中的**候选，JSON 形状
  与 AR019/AR020 产物兼容（`{"op": {"name", "steps"}}`）；
  `load_induced_skills` 可读旧格式文件。

### FR3 执行后记录钩子

- `run_skill_hierarchy`：每个子任务技能执行后，把**验证器确认的成败**
  记入统计（含失败注记，如 `element not found: ...`）；
- 记录钩子不得改变执行路径：选择、执行、回退逻辑保持不变；AR011
  30 场景套件行为不变（30/30、0 LLM）。

### FR4 能力门控联动

- `check_capability` 经 `skill_for_subtask` 自动感知淘汰：某 operation 的
  全部候选都被淘汰时，门控报 `no_skill_for_level_*`（显式缺口），
  运行时按 AR019 语义回退 LLM 兜底；缺口成功一次即可重新归纳注册
  （同名重置统计），闭环自愈。

### FR5 评测（`scripts/ar021_eval.py`）

真实 Edge（Playwright `channel=msedge`）+ 真实服务端状态 + 真实 GPU
LLM 兜底（AR004 三个适配器路径），阶段 P0–P5：

| 阶段 | 内容 |
|------|------|
| P0 | 改动后复核：多候选并存 + 选择规则 + 统计 API 存在（真实规划器） |
| P1 | 注入失效 remove 技能（唯一候选）真实执行：失败留痕、统计 0/1 淘汰、门控翻转为显式缺口；组合运行时经**真实 LLM 兜底（GPU）**完成任务 |
| P2 | 干净重归纳（AR019 链）：清空注册表 → 门控缺口 → 真实 LLM 轨迹归纳 → 注册好技能 |
| P3 | 让位证据：同一指令技能路径复跑，选中好技能、失效技能**不再被选中**（attempts 冻结）、0 LLM |
| P4 | 迁移：换商品 v1 + v2 布局 + 全量 ID churn，0 LLM |
| P5 | 组合门禁：edge pytest 套件 + AR011 30 场景（30/30、0 LLM） |

### FR6 文档

README 5.x 新章节（插入 EX001 之前，EX001 顺延）、5.1 结果表、5.6 回退
记录、AR 演进表、版本表、快速开始、目录树、徽章；`docs/REPRODUCTION.md`
复现命令；BACKLOG B02 毕业记录。

## 4. 非功能

- 既有 166 项 edge 测试不得回退（AR019/AR020 全绿为硬约束）；
- 统计钩子为纯内存操作（字典计数），真实评测耗时增量可忽略；
- 不训练新模型、不新增依赖；所有指标来自真实执行日志
  （`outputs/ar021/**`），禁止 mock / 硬编码。

## 5. 假设

- 「失败技能」由评测显式注入（BACKLOG B02 验收方式：注入一次失败技能）；
  失效形态取真实站点世代漂移的按钮文案差异（「删除」vs「移除」），
  在真实 DOM 上以 `element not found` 真实失败，不构造假错误；
- 单卡 GPU（Quadro RTX 5000 16GB）可跑 AR004 适配器（既有 AR019/AR020
  已验证）。

## 6. 术语

- 候选（candidate）：同一 operation 下注册的一个参数化模板，身份=名称；
- 淘汰（demoted）：按策略从选择集中移除、但保留在注册表与审计文件中；
- 让位（yield）：失效技能不再被选中，由更高成功率候选或 LLM 兜底接管；
- 成功率：`successes / attempts`（验证器确认口径）。
