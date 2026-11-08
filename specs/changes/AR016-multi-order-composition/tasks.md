# [AR016] 任务跟踪

| ID | 任务 | 状态 | 备注 |
|----|------|------|------|
| T001 | 服务端订单历史 | passing | site.py |
| T002 | TaskSpec 订单序列 + 验证器 | passing | tasks.py/verifier.py |
| T003 | 技能连续执行 reset=False | passing | skill_library.py |
| T004 | 序列运行时 | passing | runtime.py |
| T005 | 多订单评测 | passing | ar016_eval.py |
| T006 | 单测 | passing | |
| T007 | README/封面/复现 | passing | v4.5 |
| T008 | 同步 gitee | passing | |

## 进度记录

- 2026-11-04：AR016 启动；AR015 已归档。
- 2026-11-04：合并基线 0/2；序列 Runtime 2/2，两笔独立订单，4.3–4.4s。
- 2026-11-04：Gitee 同步完成（07fe4bf），clone 后 75 项真实测试通过。
