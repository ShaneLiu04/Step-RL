# [AR004] 任务跟踪

| 字段 | 内容 |
|------|------|
| AR 编号 | AR004 |
| 关联 srs.md | ./srs.md |
| 关联 design.md | ./design.md |
| 创建日期 | 2026-11-04 |

## 任务列表

| ID | 任务描述 | 依赖 | 状态 | 备注 |
|----|---------|------|------|------|
| T001 | 语义观测 eid/role/name | - | passing | browser.py |
| T002 | 语义动作 element 执行 | T001 | passing | browser.py |
| T003 | 观测后 ID 扰动压力模式 | T001 | passing | browser.py |
| T004 | 语义 prompt 与专家动作转换 | T001 | passing | policy.py / expert.py |
| T005 | 语义 SFT 训练 | T004 | passing | loss 0.234 |
| T006 | 语义 VGDP/Sparse 训练 | T005 | passing | 83.3% train |
| T007 | 语义层级 9 任务评测（稳定+扰动） | T002,T006 | passing | 100% / 100% |
| T008 | selector 基线扰动对照 | T003 | passing | 0% L1-L2 |
| T009 | 单测（语义解析/执行/prompt） | T001,T002,T004 | passing | 37 tests |
| T010 | README/封面/复现文档更新 | T007 | passing | v3.3 |
| T011 | 同步 gitee（小包分批） | T010 | in_progress | main |

## 进度记录

- 2026-11-04：selector 接口在观测后 ID 扰动下 L1–L2 成功率 0%，非法率 100%。
- 2026-11-04：语义 SFT 完成；语义 VGDP/Sparse 训练成功率 83.3%，非法动作 0。
- 2026-11-04：语义层级 9 任务在稳定与 ID 扰动下均 **100%**，非法动作/修复均为 0。
- 2026-11-04：最终方案保留 AR004（鲁棒性优先），AR003 归档为稳定 DOM 前最优。

## 阶段门控记录

### 2026-11-04 req 门控（自动化）

- 门控结果：PASS
- 审查项：压力条件真实、对照公平、回退规则

### 2026-11-04 design 门控（自动化）

- 门控结果：PASS
- 审查项：eid 生命周期、执行安全、训练一致性
