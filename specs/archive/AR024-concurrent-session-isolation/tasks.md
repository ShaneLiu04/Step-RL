# [AR024] 任务清单

| # | 任务 | 状态 |
|---|------|------|
| T1 | spec 三件套 + BACKLOG 认领 B07 | passing |
| T2 | 改动前基线探针（旧代码真实执行：E1 丢更新 / E2 保存交错 / E3 upsert 重复 / E4 服务端隔离对照） | passing |
| T3 | 实现 `skill_stats.py`（模块锁 + 原子替换 + 原子保存）+ `skill_library.py`（upsert 原子化 + 快照保存） | passing |
| T4 | 实现 `step_rl/edge/concurrency.py`（atomic_write_json + run_concurrent） | passing |
| T5 | 单测 `tests/test_edge_concurrency.py`（12 项） | passing |
| T6 | 主评测 `scripts/ar024_eval.py` P0–P4（真实 Edge 4 并发会话 / 并发留痕 / 并发持久化 / 串行回归，0 LLM） | passing |
| T7 | 组合门禁（并发单测 12/12 + edge 158 passed 零回退 + AR011 30 场景 30/30、0 LLM） | passing |
| T8 | README 5.24（插 EX001 前，EX001 顺延 5.25）+ 5.1/5.6/演进/版本 v4.13/快速开始/目录树/徽章/头部 + REPRODUCTION + BACKLOG B07 毕业 | passing |
| T9 | spec 归档（git mv specs/archive/）+ devflow-review 自查记录 | passing |
| T10 | gitee 双历史增量同步，收尾校验 diff 为空 | passing |

## 执行记录

- T2：`outputs/ar024/baseline_probe.json`。旧代码 E2 保存交错 **10/10 轮混合快照 + 10/10 轮
  `RuntimeError: dictionary changed size during iteration`**；E3 **2 个重复候选**；
  E4 两个真实并发会话服务端状态零串扰（隔离缺口在进程共享技能运行时层）。
- T3/T4：`skill_stats.py` / `skill_library.py` 模块锁 + 一致快照 + `atomic_write_json`；
  新增 `concurrency.py`（原子 JSON 写 + 每会话一线程一事件循环的 `run_concurrent`）。
- T5：`python -m pytest tests/test_edge_concurrency.py -q` → **12 passed**。
- T6：`outputs/ar024/eval/ar024_report.md`，P0–P4 全部 PASS：
  P1 4 并发真实 Edge **4/4 成功、零串扰**，墙钟 3.74s vs 5.80s（**2.75×**）；
  P2 真实 DOM 失败 **4/4**，统计 `attempts=4 / failures=4`，淘汰门控翻转，审计 JSON 可解析；
  P3 10 轮 × 12 写者 **0 损坏 / 0 混合快照 / 0 死写者**；
  P4 串行两任务 **0 LLM**（1.34s / 0.70s）。
- T7：并发单测 12/12；`tests/test_edge_*.py` **158 passed**；
  全量 `pytest tests` **237 passed / 10 failed / 3 skipped**——10 项失败仅因本机代理阻断
  `gpt2` 下载，父提交 `4fedd75` 对照同为该 10 项，AR024 零回退；
  `python scripts/ar011_eval.py` → **30/30，policy_steps=0，prompt_tokens=0，81.94s**。
- T8：README v4.13 / 5.24 / 5.6 / 演进 / 版本表 / 快速开始 / 目录树 / 徽章 / 头部，
  `docs/REPRODUCTION.md`，`specs/BACKLOG.md` B07 毕业。
- T9：归档 `specs/archive/AR024-concurrent-session-isolation/`。
- T10：Gitee 增量同步并校验 `git diff -w gitee/main main` 为空。

## devflow-review 独立自查（findings + verdict）

- Finding 1：锁内不得做 I/O。实现将快照构建留在锁内、文件写移到锁外 `atomic_write_json`，
  P4 串行耗时与既有评测同量级，通过。
- Finding 2：`load` 语义必须保持「后到者胜」且形状不变。既有 AR021 测试与审计 JSON
  逐字段可读，通过。
- Finding 3：`os.replace` 在 Windows 可能短暂被占用。实现带有限重试，P3 10×12 并发写者
  0 损坏，通过。
- Finding 4：并发执行器异常必须按会话隔离。P2 四会话全部真实失败仍返回各自槽位，
  其余流程不受影响，通过。
- Verdict：**PASS**。保留 AR024（真实 4 并发零串扰 + 精确留痕 + 原子持久化 + 串行零回退）。
