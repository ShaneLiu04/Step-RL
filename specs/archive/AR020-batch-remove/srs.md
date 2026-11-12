# [AR020] 需求设计说明书

| 字段 | 内容 |
|------|------|
| AR 编号 | AR020 |
| AR 主题 | batch-remove（多商品批量移除：批量解析 + 多目标模板实例化） |
| 日期 | 2026-11-12 |
| 状态 | Draft |
| 取材 | specs/BACKLOG.md B01 |

## 1. 背景与目标

AR019 从**单商品**移除轨迹归纳出 remove 技能：模板以 `{product}` 为
单位，`_materialize` 只对 `task.targets` 的**第一个** pid 做实例化。
「清空 p3 和 p4」一类的批量指令存在两个真实缺陷，改动前基线探针
（`outputs/ar020/baseline_probe.json`，在改动前提交上执行）给出证据：

1. **规划层**：planner remove 分支只取 `mentions[0]`，第二个商品在规划
   阶段即丢失（批量指令被规划成单商品任务）；
2. **实例化层**：即使手工构造正确的批量 TaskSpec，旧 `_materialize`
   也只替换第一个 pid —— 技能只点一次「移除」，另一商品仍留在购物车，
   多目标 `cart_without` 谓词必然判负。

AR020 目标：

1. 批量移除指令（≥2 商品）被**完整**规划（targets 含全部提及商品）；
2. 单商品归纳模板按 targets **逐目标展开**实例化（前缀一次 + 每商品单元
   循环 + 后缀一次）；
3. 批量任务技能路径 3/3、0 LLM（v1 双商品、v1 三商品、v2+ID churn 双商品）；
4. 单商品移除不回退：镜像 AR019 P3/P4 的 3 条任务 3/3、0 LLM；
5. 组合门禁不低于现状（edge ≥153 passed、AR011 30/30 0 LLM）。

不达标即按 design.md §9.1 回退。

## 2. 范围

**In：**

- `planner.py` remove 分支批量解析（全部 mentions → `targets`/`seed_cart`）；
- `skill_library.py` `_materialize` 多目标展开（prefix/unit/suffix 语义）；
- `skill_induction.py` `collapse_repeated_product_steps`（批量轨迹泛化：
  占位符替换后连续同步步折叠为一个；单商品轨迹为 no-op，AR019 输出不变）；
- `scripts/ar020_baseline_probe.py`（改动前执行，产物入库前提交）；
- `scripts/ar020_eval.py` 真实评测（LLM 兜底 → 归纳 → 批量复用 → 单商品
  回归 → 组合门禁）；
- `tests/test_edge_batch_remove.py` 单测；
- README / REPRODUCTION / BACKLOG / gitee 同步。

**Out：**

- 新模型训练（P1 兜底复用 AR004 三个适配器）；
- 服务端 `/remove/{pid}` 路由改动（一次点击删一个商品保持不变，批量是
  技能侧的动作序列，不是新端点）;
- 验证器 `cart_without` 改动（已支持多目标：全部 targets 数量为 0）；
- AR019 单商品归纳行为的改动（单商品轨迹经 `induce_skill` 的输出与改动前
  逐步一致）。

## 3. 功能需求

### FR1 规划器批量解析

- 指令含「移除/删除」且命中 ≥1 个商品：`targets={pid: 0 for pid, _ in
  mentions}`（全部提及商品，文本顺序）、`seed_cart={pid: max(qty, 1)}`、
  `operation="remove"`、`predicates=["cart_without"]`、`start_path="/cart"`；
- 单商品指令的 TaskSpec 与改动前**完全一致**（向后兼容）。

### FR2 多目标模板实例化

- `_materialize` 按 `task.targets` 的插入序展开：
  - **前缀** = 模板中首个含 `{product}` 的步骤之前的部分，只实例化一次；
  - **每商品单元** = 从首个 `{product}` 步骤起的连续 `{product}` 步骤段，
    对每个目标 pid 各实例化一次；
  - **后缀** = 单元之后的部分，实例化一次（占位取第一个目标）；
- 单目标任务：展开后的步骤序列与旧实现逐步一致（bit 级兼容）。

### FR3 批量轨迹归纳

- `induce_batch_template(task, records, catalog)`：按真实「移除 <商品>」
  点击切分逐商品块；块 = 首个引用商品的记录 → 该商品移除点击；引用商品
  之前不引用商品的记录为前缀；
- 每块泛化后取**最长公共后缀**作为每商品单元（真实 P1 轨迹块为前缀
  单调而非严格相等，公共后缀是"对每件商品都被证明有效"的最小模式）；
- 成功轨迹每块以各自 `移除 {product}` 收尾 → 单元非空且以移除步收尾；
  块数 <2 或后缀为空 → 返回 `None`（显式能力缺口，不注册、不伪造）；
- AR019 单商品路径 `induce_skill` 输出逐字段不变。

### FR4 能力门控

- 门控逻辑不改：批量指令经 planner 产出批量 TaskSpec 后，
  `skill_for_subtask` 按 `operation="remove"` 命中诱导注册表 → covered；
- 未注册非 add 操作仍显式返回 None（AR019 守卫不变）。

### FR5 评测（`scripts/ar020_eval.py`）

| 阶段 | 内容 | 判定 |
|------|------|------|
| P0 | 改动后复核：批量指令规划完整（targets 全量）+ 注册后批量指令门控 covered | 两条都过（改动前基线探针已在旧代码上留证） |
| P1 | 真实 LLM 兜底执行批量任务（p3+p4，seed 2/3，TrajectoryRecorder 全程记录） | 真实成功 |
| P2 | 归纳（批量轨迹 → 单商品单元模板）→ 注册 → 持久化 JSON | 模板恰含一个「移除 {product}」点击 |
| P3 | 批量技能复跑 ×3：B1 p3+p4（v1）；B2 p2+p3 三数量（v1）；B3 p4+p2（v2 + ID churn） | 3/3、0 LLM、cart 为空 |
| P4 | 单商品回归 ×3（镜像 AR019）：S1 p3 v1；S2 p4 v1；S3 p3 v2+churn | 3/3、0 LLM |
| P5 | 组合门禁：edge pytest 套件 + AR011 30 场景 | rc=0 且不低于基线（153 passed、30/30、0 LLM） |

## 4. 非功能

| 类型 | 要求 |
|------|------|
| 真实性 | 全链路真实浏览器（msedge headless）/真实 GPU 推理/真实服务端状态，无 mock |
| 端侧收益 | 批量/单商品复用均 0 LLM 调用、0 prompt tokens |
| 可复现 | 固定 seed=42、JSON 产物、固定适配器路径（outputs/ar004/*） |
| 安全 | URL 白名单、动作白名单、语义定位均沿用现状 |

## 5. 假设

- AR004 三个适配器产物在位（P1 兜底）；
- LLM 兜底能在购物车页完成两次连续「移除」点击（难度与 AR019 单商品
  相当，AR019 P1 已验证单点击可行）；
- 每商品步幂等：移除按钮点击后商品离车、按钮消失，同商品重复点击不存在；
  若真实批量轨迹出现非幂等重复，如实记录并放弃归纳（按 §9.1 回退）。

## 6. 术语

| 术语 | 定义 |
|------|------|
| 批量移除 | 单条指令内移除 ≥2 个购物车商品 |
| 每商品单元 | 模板中一段连续含 `{product}` 的步骤，是"对一件商品做一遍"的最小单位 |
| 多目标实例化 | 模板 = 前缀 + 单元×N + 后缀，N = len(task.targets) |
| 批量轨迹 | LLM 兜底完成批量任务时记录的真实动作序列 |
