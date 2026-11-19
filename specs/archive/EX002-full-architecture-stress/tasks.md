# [EX002] 任务清单

| # | 任务 | 状态 |
|---|------|------|
| T1 | E1 真实重跑（selector/semantic × 5 扰动） | passing |
| T2 | E2 真实重跑（扁平 9 任务） | passing |
| T3 | E3 真实重跑（移除验证器观测 9 任务） | passing |
| T4 | E4–E8 汇总真实 AR011/012/016–18/024–26 产物 | passing |
| T5 | `scripts/ex002_summary.py` + `summary.json` | passing |
| T6 | `scripts/ex002_figures.py` + 6 图 | passing |
| T7 | `docs/results/EX002_report.md` + `docs/EXPERIMENTS_EX002.md` | passing |
| T8 | 全 AR 覆盖矩阵与组合回退决策 | passing |
| T9 | 归档与 Gitee 同步 | passing（`main=54145e0`；全新 clone：报告/6 图/spec 均存在） |

## 执行记录

- E1（2026-11-19 重跑）：selector 0.00/0.25/0.50/0.75/1.0 =
  **100/50/50/0/0%**，非法动作 0/13/14/21/28；semantic 全 100%、0 非法。
- E2：扁平 **8/9（88.9%）**，失败 `ev_multi_p3p4`（Φ=0.62）；层级 **9/9**。
- E3：移除验证器观测 **3/9（33.3%）**、平均 11.0 步；保留 9/9、6.33 步。
- E4：v1/v2 30/30；v3 固定 1/3 → LASC 3/3，0 LLM。
- E5：observe 440→328、往返 1760→656（−62.7%）、耗时 10.96→4.06s（−63.0%）。
- E6：4 并发 4/4 零串扰（2.75×）；失败留痕 4/4；10×12 写者 0 损坏；
  AR012 30/30、0 GPU、2.73×。
- E7：AR016 0/2→2/2；AR017 0/2→2/2；AR018 0/3→3/3。
- E8：AR011 30/30、0 LLM、0 tokens、77.38s；edge 169 passed。

## 结论

**PASS**：现有组合在压力矩阵下未出现新回退；负结果/回退项明确；
全 AR 覆盖矩阵完成。
