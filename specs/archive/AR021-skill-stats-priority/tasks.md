# [AR021] 任务清单

| # | 任务 | 状态 |
|---|------|------|
| T1 | spec 三件套 + BACKLOG 认领 B02 | passing（commit 11042b4） |
| T2 | 改动前基线探针（旧代码真实执行） | passing（探针 outputs/ar021/baseline_probe.json：单槽覆盖 + 失效技能两次重选 + 失败后仍 covered） |
| T3 | 实现 `step_rl/edge/skill_stats.py` | passing（commit ceec6a4） |
| T4 | 升级 `skill_library.py`（多候选 upsert + 选择 + 记录钩子） | passing（commit ceec6a4） |
| T5 | 单测 `tests/test_edge_skill_stats.py`（13 项：8 纯逻辑 + 2 真实浏览器 + 持久化兼容） | passing（13/13；全套件 179 passed, 3 skipped, 68.39s） |
| T6 | 组合门禁预跑（改动后） | passing（179 passed = 166 基线 + 13 新增，零回退） |
| T7 | 主评测 `scripts/ar021_eval.py` P0–P5 | passing（decision=keep；P1 真实 DOM 失败 0/1→demoted + GPU 兜底 1098 tokens 17.72s；P2 重归纳 1092/89 tokens 16.18s；P3 让位 1.61s 0 LLM；P4 迁移 1.59–1.64s；P5 pytest 179 passed + AR011 30/30 0 LLM） |
| T8 | README 5.21（插 EX001 前，EX001 顺延 5.22）+ 5.1/5.6/演进/版本/快速开始/目录树/徽章 + REPRODUCTION | passing |
| T9 | BACKLOG B02 毕业、tasks 全部 passing、spec 归档 | passing |
| T10 | gitee 双历史增量同步，收尾校验 diff 为空 | pending |

## 执行记录

- **T2 基线探针（旧代码，AR020 状态）**：A 单槽——先注册 tpl_x 再注册 tpl_y，
  物化步骤只剩 `["", "删除 无线充电器"]`（tpl_x 被覆盖），统计 API 不存在；
  B 无记忆——两次全新会话真实执行移除 p3，均失败（cart 保持 `{"p3": 2}`），
  选中技能两次同为 `induced_remove_stale`，失败后门控仍 `covered=true`。
- **T7 评测真实数字**（`outputs/ar021/eval/ar021_results.json`）：
  P1 失效技能 `element not found: 删除 无线充电器`，统计 0/1 →
  `success_rate 0.00 < 0.50 after 1 attempt(s)` demoted，门控
  `no_skill_for_level_2`，组合运行时 LLM 兜底 4 步 1098 prompt tokens
  17.72s cart 清空；P2 干净重归纳 4 步模板（1092/89 tokens，16.18s），
  注册候选 `[induced_remove_stale, induced_remove]`，门控翻回 covered；
  P3 选中 `induced_remove`（stale attempts 冻结 1），0 LLM 1.61s；
  P4 p4 v1 1.59s / p3 v2 churn 1.64s 均 0 LLM；P5 pytest 179 passed
  3 skipped（70.69s），AR011 rc=0 policy_steps=0。
- **T10 gitee 同步**：按 AGENTS.md §6 执行（worktree 增量、~50KB/提交、
  结束 `git diff -w --stat gitee/main main` 为空）。

## devflow-review 独立自查（findings + verdict）

对 spec / 代码 / 评测产物按独立评审标准复查：

1. **[minor] `rank_candidates` 排序 key 内重复调用 `get_skill_stat`**：
   每候选两次字典查找；数据规模（技能数 ≤ 双位数）下无实际影响，不改。
2. **[info] 淘汰 sticky 为有意设计**：0/1 淘汰后即使技能后续真实成功也
   不自动恢复，恢复路径 = 同名再注册（新轨迹=新证据，统计重置）或显式
   `reset_skill_stats`。避免「失败一次淘汰 / 成功一次恢复」的统计振荡；
   已写入 README 5.21 安全边界。
3. **[info] 未测试与恒失败在排序上同记 0.0**：设计 D5 的有意选择
   （被证明的技能恒 ≥0.5 必然优先；未测试按注册序）；`SkillStat` 字段
   本身可区分（attempts=0）。
4. **[verified] 兼容性**：单候选 `save_induced_skills` 输出与 AR019/AR020
   产物逐字段一致（`test_save_single_candidate_matches_legacy_shape`）；
   旧格式文件可加载（`test_load_legacy_artifact_shape`）；AR019/AR020
   全部既有测试（11 + 12 项）零回退。
5. **[verified] 成败口径**：记录点唯一（`run_skill_hierarchy` 验证器确认
   `compute_progress(...).success` 之后），模型/技能不得自述成功；
   fallback LLM 的成功不归因给技能。
6. **[verified] 指标来源**：README 5.21 全部数字来自
   `outputs/ar021/**` 真实执行日志，无 mock / 硬编码。
7. **[info] 模块级 `_ORDER` 计数器进程重启归零**：仅进程内 tie-break 用，
   持久化用 `registered_at` ISO 时间戳，跨进程不影响审计语义。

**verdict：PASS（keep）**——无阻断性 finding；兼容性、验证口径与门禁
证据均复核通过；组合门禁（§9.1 规则）全过，组合最优前移至 AR021。
