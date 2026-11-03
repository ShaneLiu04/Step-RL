# [AR001] 任务跟踪

| 字段 | 内容 |
|------|------|
| AR 编号 | AR001 |
| 关联 srs.md | ./srs.md |
| 关联 design.md | ./design.md |
| 创建日期 | 2026-11-03 |

## 任务列表

| ID | 任务描述 | 依赖 | 状态 | 备注 |
|----|---------|------|------|------|
| T001 | 真实本地商城服务 + 服务端状态 API | - | passing | site.py |
| T002 | 任务规格、训练/留出划分、进度验证器 | T001 | passing | tasks.py / verifier.py |
| T003 | Playwright(msedge) 真实环境 + 观测 + 动作执行 | T001 | passing | browser.py |
| T004 | 专家轨迹采集（真实交互） | T002,T003 | passing | expert.py |
| T005 | Prompt/JSON 解析/DOM 接地修复 | T003 | passing | policy.py |
| T006 | LoRA SFT（response-only） | T004 | passing | sft.py |
| T007 | 真实 rollout + Φ 奖励采集 | T003,T005,T006 | passing | rollout.py |
| T008 | 步级 GRPO + VGDP + KL | T007 | passing | step_grpo.py |
| T009 | 四组合真实评测矩阵与报告 | T006,T008 | passing | evaluate.py |
| T010 | site/verifier/policy 单元测试 | T001,T002,T005 | passing | tests/test_edge_*.py |
| T011 | 修复既有阻断：config 映射/finish/KL/任务注册 | - | passing | 最小改动 |
| T012 | GPU 训练与四组对比实验，记录真实指标 | T009 | passing | outputs/ar001 + docs/results |
| T013 | 回填 README/复现文档并同步 gitee | T012 | in_progress | 含 gitee 推送 |

## 状态说明

- `pending`：待开始
- `in_progress`：进行中（当前会话）
- `passing`：开发完成，测试通过
- `failed`：测试失败，需修复

## 进度记录

- 2026-11-03：需求/设计基线完成，开始实现真实环境与验证器。
- 2026-11-04：真实 HTTP 商城 + Edge 环境 + 验证器完成；专家 14/14 成功。
- 2026-11-04：SFT（Qwen3-0.6B LoRA，68 对真实轨迹）完成，L1-L2 留出 4/4。
- 2026-11-04：VGDP / Sparse 对照完成；L3 留出任务 VGDP 2/2，Sparse 0/2。
- 2026-11-04：9 任务全量矩阵完成：SFT 44.4% / +repair 55.6% / sparse 55.6% / vgdp 66.7% / 路由组合 77.8%。
- 负结果保留：L4 数量2+结算 0%，L5 多商品 0%。

## 阶段门控记录

### 2026-11-03 req 门控（自动化）

- 门控结果：PASS
- 审查项：范围清晰、验收可测、无 mock 结论、组合回退规则明确
- 审查代理：self（用户授权全自动）

### 2026-11-03 design 门控（自动化）

- 门控结果：PASS
- 审查项：模块边界、算法正确性、实验矩阵、风险与回退
- 审查代理：self（用户授权全自动）
