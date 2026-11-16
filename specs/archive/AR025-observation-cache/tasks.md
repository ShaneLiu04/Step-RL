# [AR025] 任务清单

| # | 任务 | 状态 |
|---|------|------|
| T1 | spec 三件套 + BACKLOG B08 认领 | passing |
| T2 | 改动前基线探针（真实 Edge 30 场景：observe 次数/耗时/相邻重复） | passing |
| T3 | 实现 `browser.py` 单往返快照 + MutationObserver 修订号 + 缓存 | passing |
| T4 | 实现技能层观测复用（`run_skill` / `run_skill_hierarchy`） | passing |
| T5 | 单测 `tests/test_edge_observation_cache.py`（真实 Edge/HTTP） | passing |
| T6 | 主评测 `scripts/ar025_eval.py` P0–P4（30 场景 / 缓存正确性 / 往返/耗时 / 门禁） | passing |
| T7 | 组合门禁（edge 套件零回退 + AR011 30/30 0 LLM） | passing |
| T8 | README v4.14 / REPRODUCTION / 大模型配置 / 封面 / BACKLOG 毕业 | passing |
| T9 | spec 归档 + devflow-review 自查 | passing |
| T10 | Gitee 小包同步 + 全新 clone 复现验证 | passing |

## 执行记录

- T2 基线（真实 Edge 30 场景，旧 4 往返 + 旧技能重复观测）：
  observe **440 次 / 10.96s**，浏览器往返 **1760**，相邻重复 **166（37.7%）**；
  30/30、0 LLM。
- T3：`browser.py` 注入 MutationObserver（忽略 data-eid），`_META_JS` 单次返回
  rev/doc/url/title + 实时 `/api/state`；缓存命中复用元素/文本、state 永不缓存；
  `type` 主动失效；导航/doc/URL 变化失效。
- T4：`run_skill(initial_obs=...)` 复用调用方观测；`SkillResult.observation` 返回末次
  观测；`run_skill_hierarchy` 删除技能后重复 observe。
- T5：`python -m pytest tests/test_edge_observation_cache.py -q` → **6 passed**。
- T6：`outputs/ar025/eval/ar025_summary.json`，P0–P4 全部 true：
  30/30、policy_steps=0、prompt_tokens=0；
  observe 440→328；往返 1760→656（**−62.7%**）；observe 10.96s→4.06s（**−63.0%**）；
  独立真实缓存探针 4 次调用 **3 命中 / 1 扫描**，元素稳定、state 实时；
  总墙钟 81.65s→76.71s。
- T7：edge 套件 **164 passed**；全量 `pytest tests` **243 passed / 10 个既有
  代理环境失败 / 3 skipped**（与 AR024 基线同类，零新增失败）；
  AR011 30 场景在主评测中 **30/30、0 LLM**。
- T8：README v4.14 / 5.25 / 5.6 / 演进 / 版本表 / 快速开始 / 目录树 / 徽章 /
  大模型实验口径；`docs/REPRODUCTION.md` §4.5.1 大模型 AOC on/off 配置；
  `specs/BACKLOG.md` B08 毕业。
- T9：归档 `specs/archive/AR025-observation-cache/`。
- T10：Gitee 增量小包同步并校验 diff 为空；全新 clone 跑缓存测试。

## devflow-review 独立自查（findings + verdict）

- Finding 1：缓存不得跨页复用。键含每 document 随机 `doc` + URL；导航后
  init script 重新分配，真实测试覆盖 DOM 变化/导航失效，通过。
- Finding 2：state 不得过期。state 永不进入缓存，每次 observe 实时
  `fetch('/api/state')`，缓存探针验证 state_live，通过。
- Finding 3：type 的 value 变化不触发 mutation。`execute(type)` 主动失效缓存，
  真实测试断言新值 `iphone`，通过。
- Finding 4：技能层复用观测可能误判进度。只用同一动作后的末次观测；
  30 场景 30/30、skill_steps 276 与基线一致，通过。
- Finding 5：30 场景技能路径无缓存命中，不能夸大缓存收益。主评测单独报告
  技能路径 0 命中，并用独立真实重复/wait 探针验证缓存，通过。
- Verdict：**PASS**。保留 AR025（往返 −62.7%、observe 耗时 −63.0%，
  30/30 与 0 LLM 零回退）。
