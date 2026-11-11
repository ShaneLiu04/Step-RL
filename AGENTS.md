# AGENTS.md — Step-RL 开发与复现约束

## 1. 真实性红线

- 任何**实验结论、README 指标、图表**必须来自真实执行日志（`outputs/ar001/**`）。
- 禁止把 `generate_mock_results()`、随机数、硬编码数组当作结果。
- 旧 `--mock` 路径只能用于冒烟测试，不得进入报告。
- 不允许静默降级为“成功”；失败必须显式返回错误。

## 2. 环境

| 项 | 值 |
|----|----|
| OS | Windows 11 |
| Python | 3.11 |
| PyTorch | 2.5.1+cu121 |
| GPU | Quadro RTX 5000 16GB |
| Transformers | 5.15.1 |
| PEFT | 0.20.0 |
| 浏览器 | 系统 Edge，Playwright `channel="msedge"` |
| 基座模型 | 本地缓存 `Qwen/Qwen3.5-0.8B-Base` |

> Playwright 自带 Chromium 下载被企业代理拦截（407）；必须使用系统 Edge，不得改用 mock 浏览器。

## 3. 测试

```powershell
$env:PYTHONPATH="D:\agentRL\Step-RL"
python -m pytest tests/test_edge_site.py tests/test_edge_verifier.py tests/test_edge_policy.py -v
python -m pytest tests -q
```

## 4. 真实实验

```powershell
$env:PYTHONPATH="D:\agentRL\Step-RL"
python scripts/edge_pipeline.py --stage all --quick
```

产物：

```
outputs/ar001/
  sft_adapter/
  rollout_train.jsonl
  grpo_sparse/
  grpo_vgdp/
  eval_report.json
  eval_report.md
```

## 5. 设计纪律

- 新能力放在 `step_rl/edge/`，避免破坏旧模块。
- 旧训练器只修复阻断真实运行的缺陷，不做无关重构。
- 每次改动必须可测试；新增核心模块要有单测。
- 组合创新必须按 `specs/changes/AR001-*/design.md §9.1` 回退规则记录。

## 6. Gitee 推送

- 远端：`https://gitee.com/liu-xingyan04/step-rl.git`（分支 `main`）
- 企业代理对 >~100KB 的 POST 返回 403；禁止一次性 force-push 本地全量历史。
- **双历史纪律**：本地 `main` 是真实开发历史；远端 `main` 是「sync 历史」
  （前序会话为绕开代理限制构建，与本地无共同祖先）。二者并存是常态，
  不要试图用本地历史覆盖远端。
- **标准同步流程（增量 sync 提交）**：
  1. `git fetch gitee && git diff -w --name-status gitee/main main` 得到真实
     内容增量（`-w` 剔除换行符噪声）；
  2. `git worktree add D:\agentRL\_sync_wt gitee/main`；
  3. 在 worktree 内 `git checkout main -- <增量路径>`，按 ~50KB 一组拆成
     多个小提交，每提交后立即 `git push gitee HEAD:main`；
  4. 需在远端删除路径时用 `git update-index --force-remove <paths>` 后
     直接 commit（不要随后再 `git add` 同目录），`git rm` 会被环境拦截；
  5. 结束后 `git diff -w --stat gitee/main main` 必须为空（内容一致）。
- 不得把 PAT 写入仓库文件；凭据只保存在本机 credential store。

## 7. AR / EX 命名规范

- 创新 AR：`ARxxx-topic`，编号连续，不得被实验类占用。
- 实验/归因/验收：`EXxxx-topic`，与 AR 编号体系独立。
- 实验类文档只描述验证设计、指标、结论；创新代码/架构仍走 AR。
- 已完成 AR/EX 均移入 `specs/archive/`。
