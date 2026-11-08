# [AR013] 任务跟踪

| ID | 任务 | 状态 | 备注 |
|----|------|------|------|
| T001 | 对抗 UI 注入 | passing | site.py |
| T002 | 技能精确 role/name 接地 | passing | skill_library.py |
| T003 | baseline vs runtime 评测 | passing | ar013_eval.py |
| T004 | 单测 | passing | |
| T005 | README/封面/复现 | passing | v4.2 |
| T006 | 同步 gitee | passing | |

## 进度记录

- 2026-11-04：AR013 启动；AR012 已归档。
- 2026-11-04：role=link 伪装未诱导基线（3/3）；升级 role=button 后基线 0/3、Runtime 3/3。
- 2026-11-04：Runtime 订单精确、2.7–3.7s vs 基线 65–89s。
