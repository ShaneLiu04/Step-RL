# [AR020] 任务清单

> 状态：pending → in_progress → passing。全部 passing 且组合门禁通过后
> 随规格整体移入 `specs/archive/AR020-batch-remove/`。

- [x] T1 BACKLOG 登记：B01 标记 `claimed by AR020` — passing
- [x] T2 规格三件套（srs/design/tasks，含 design §9.1 组合回退规则） — passing
- [x] T3 改动前基线探针 `scripts/ar020_baseline_probe.py` 执行并留证
      （outputs/ar020/baseline_probe.json + .md，旧代码上运行） — passing
- [x] T4 planner remove 分支批量解析（FR1，单商品向后兼容） — passing
- [x] T5 `skill_library._materialize` 多目标展开（FR2，prefix/unit/suffix） — passing
- [x] T6 `skill_induction`：块式切分 + 最长公共后缀 unit（FR3，AR019 输出不变） — passing
- [x] T7 单测 `tests/test_edge_batch_remove.py`（13 项，含真实浏览器批量移除） — passing
- [x] T8 `scripts/ar020_eval.py` 真实评测 P0–P5（含 GPU LLM 兜底、GPU 显存/
      token/耗时记录） — passing
- [x] T9 组合门禁：edge pytest ≥153 passed、AR011 30/30 0 LLM（真实执行） — passing
- [x] T10 README（v4.9、AR 表、5.x 章节、组合回退记录、快速开始、目录树、
      徽章、cover）+ docs/REPRODUCTION.md + BACKLOG 毕业 — passing
- [ ] T11 本地 git mv 归档 specs/changes/AR020 → specs/archive/ — in_progress
- [ ] T12 gitee 双历史同步（AGENTS.md §6：worktree 增量、逐包 ≤50KB、
      收尾 `git diff -w --stat gitee/main main` 为空） — in_progress

## 执行记录

### T3 改动前基线探针（旧代码，commit cc7ade5 之前状态）

真实 Edge + 真实 server（`outputs/ar020/baseline_probe.{json,md}`）：

- A 规划：批量指令 → `targets={"p3": 0}`，**第二商品 p4 丢失**；
- B 批量（旧实例化）：`success=false`，最终购物车 `{"p4": 3}`（只删了 p3）；
- C 单商品对照：`success=true`，购物车 `{}`（环境/模板本身可用，缺陷只在批量链路）。

### T7/T8 单测与真实评测（commit 002c119，全部真实执行）

- 单测 13/13 通过（含真实 Edge 批量移除：seed p3×2 + p4×3 → cart `{}`）；
- AR019 既有测试 11/11 通过（`induce_skill` 输出逐字段不变）；
- 全链路（`outputs/ar020/eval/ar020_results.json`）：
  - P0a 规划完整：`targets={"p3": 0, "p2": 0}`，seed `{p3: 2, p2: 3}`；
  - P1 真实 LLM 兜底（GPU，AR004 适配器，seed=42）：**成功**，4 步，
    1267 prompt tokens / 96 response tokens，19.22s；
  - P2 归纳：块式切分（真实「移除」点击边界）+ 最长公共后缀 →
    模板 2 步（游离 type 前缀 + `移除 {product}` 单元），注册后
    `covered=true`；双目标任务实例化 3 步；
  - P3 批量复跑（0 LLM / 0 tokens，cart 全空）：B1 v1 1.83s、
    B2 v1 带数量 1.80s、B3 v2+churn 1.85s —— **3/3**；
  - P4 单商品回归（镜像 AR019，0 LLM）：S1 v1 1.54s、S2 v1 1.53s、
    S3 v2+churn 1.54s —— **3/3**；
  - 同任务（双商品）LLM 19.22s → 技能 1.83s ≈ **10.5×**。

### T9 组合门禁（真实执行，P5）

- edge 套件：`166 passed, 3 skipped`（rc=0，68s；≥ 基线 153，含 13 项新增）；
- AR011 30 场景：rc=0，30/30，0 LLM（policy_steps=0，85.7s）；
- 遗留技术债不变：legacy 三文件（locator/progress_estimator/smart_wait）
  17 个历史失败，AR019 git-stash 对照验证与本 AR 无关，不纳入门禁。

**决策：keep（组合保留，AR020 为当前最终保留组合）。**

### T10–T12 文档与同步

- README v4.9：徽章 166、AR 表 + §5.21 + 组合回退记录 + 快速开始 + 目录树
  + 版本表；cover 重新生成（71,411 B，< 100KB 代理上限）；
- REPRODUCTION：补 AR019 漏登记 + 新增 AR020（命令 22/23、产物、§3.2、
  §3.2.16）；
- BACKLOG：B01 毕业登记；
- T11/T12（归档 + gitee 同步）执行后回填。
