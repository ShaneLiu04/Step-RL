# [AR026] 任务清单

| # | 任务 | 状态 |
|---|------|------|
| T1 | spec 三件套 + BACKLOG B06 认领 | passing |
| T2 | 真实 v3 布局（无 id/searchbox/步进器） | passing |
| T3 | 观测支持 `[role=spinbutton]` + aria-valuenow | passing |
| T4 | LASC：`set_quantity` + 角色/名称别名 + adaptive 消融 | passing |
| T5 | 真实测试 `tests/test_edge_layout_v3_adaptive.py`（5 项） | passing |
| T6 | 主评测 `scripts/ar026_eval.py`（baseline vs adaptive，真实 Edge/0 LLM） | passing |
| T7 | 组合门禁（edge 169 passed + AR011 30/30 0 LLM） | passing |
| T8 | README v4.15 / REPRODUCTION / 大模型配置 / 封面 / BACKLOG 毕业 | passing |
| T9 | spec 归档 + devflow-review 自查 | passing |
| T10 | Gitee 小包同步 + 全新 clone 复现验证 | passing |

## 执行记录

- T2/T3：v3 无 id、`role=searchbox`/“查找”、`span[role=spinbutton]` +
  “增加/减少数量” + hidden qty；观测 selector 增加 `[role=spinbutton]`，
  value 回退 `aria-valuenow`。
- T4：`set_quantity` 在 input 上走 type，在步进器上读当前 `aria-valuenow`
  按差值点击；`ROLE_ALIASES`/`NAME_ALIASES` 支持 searchbox/查找；
  `adaptive=False` 保留旧技能作为真实 baseline。
- T5：`python -m pytest tests/test_edge_layout_v3_adaptive.py -q` → **5 passed**。
- T6：`outputs/ar026/eval/ar026_results.json`：
  baseline（固定技能）**1/3**，LASC **3/3**，均 0 LLM / 0 prompt tokens；
  v3 加购/改量 baseline 真实报错 `Element is not an <input>`，LASC 成功。
- T7：edge 套件 **169 passed**；AR011 **30/30、0 LLM、0 tokens、77.38s**；
  全量（排除既有 gpt2 网络文件）**243 passed / 3 skipped**，已知环境失败
  仍为同一 10 项，零新增。中途发现 `set_quantity` 对无 aria-label 的旧版
  数量输入回归，已修复并复跑 30/30 后保留。
- T8：README v4.15 / 5.26 / 5.6 / 演进 / 版本表 / 快速开始 / 目录树 / 徽章 /
  大模型实验口径；REPRODUCTION 新增 AR026 命令、产物与大模型复现说明；
  BACKLOG B06 毕业。
- T9：归档 `specs/archive/AR026-layout-adaptive-skill-compilation/`。
- T10：Gitee 5 个增量小包推送完成，`gitee/main = e51abce`；
  `git diff -w gitee/main main` 为空；全新 `--depth 1` clone 中
  `tests/test_edge_layout_v3_adaptive.py` **5 passed**，README v4.15 / AR026 章节 /
  LASC 3/3 均存在。

## devflow-review 独立自查（findings + verdict）

- Finding 1：v3 的 hidden qty 未随步进器更新。inline JS 改用
  `this.form.querySelector('.qty-input')`，真实测试断言 cart p3=2/3，通过。
- Finding 2：旧版数量 input 没有 aria-label。`set_quantity` fallback 到
  任意 spinbutton；真实 v1 debug 与 AR011 30/30 验证，通过。
- Finding 3：别名可能误匹配。仅对 textbox/searchbox 与搜索/查找做别名，
  真实 v3 与 v1/v2 双向覆盖，通过。
- Finding 4：baseline 必须真实失败而非 mock。`adaptive=False` 走同一真实
  v3 站点并真实报 `Element is not an <input>`，通过。
- Verdict：**PASS**。保留 AR026（v3 baseline 1/3 → LASC 3/3，0 LLM；
  AR011 30/30 与 AR025 观测指标零回退）。
