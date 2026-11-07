# [AR008] 任务跟踪

| ID | 任务 | 状态 | 备注 |
|----|------|------|------|
| T001 | 相关性评分与裁剪 | passing | observation.py |
| T002 | rollout/hierarchy 集成 | passing | observation_pruning |
| T003 | 9 任务 full vs pruned 评测 | passing | ar008_eval.py |
| T004 | token/延迟对比 | passing | |
| T005 | 单测 | passing | |
| T006 | README/封面/复现 | passing | v3.7 |
| T007 | 同步 gitee | passing | |

## 进度记录

- 2026-11-04：AR008 启动；AR007 已归档。
- 2026-11-04：相关性 top-K 裁剪 60%，回退；历史行压缩 0%，回退。
- 2026-11-04：仅移除干扰控件 100%，prompt tokens -4.2%，保留为效率层；30% 目标未达到。
- 2026-11-04：Gitee 同步完成（d168b92），clone 后 54 项真实测试通过。
