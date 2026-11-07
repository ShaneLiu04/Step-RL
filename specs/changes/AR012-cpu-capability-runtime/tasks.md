# [AR012] 任务跟踪

| ID | 任务 | 状态 | 备注 |
|----|------|------|------|
| T001 | 能力覆盖检测 | passing | capability.py |
| T002 | model=None 门控 | passing | runtime.py |
| T003 | CPU-only 30 场景 | passing | ar012_cpu.py |
| T004 | 4 路并发 | passing | |
| T005 | 未覆盖指令 | passing | unsupported |
| T006 | 单测 | passing | |
| T007 | README/封面/复现 | passing | v4.1 |
| T008 | 同步 gitee | passing | |

## 进度记录

- 2026-11-04：AR012 启动；AR011 已归档。
- 2026-11-04：30 场景 CPU-only 30/30，0 GPU/0 LLM；串行 12 任务 35.97s，4 路并发 13.16s（约 2.7×）。
- 2026-11-04：修复能力门控漏洞：无购物意图的指令不再默认执行，返回 fallback_required。
