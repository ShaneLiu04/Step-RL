# AR029 ST 验收用例（第一阶段）

> 真实 JD 用例需要用户现场登录；未执行前不得标记 PASS。本地/框架用例已真实执行。

## ST-01 SiteAdapter 契约一致性

- 前置：`PYTHONPATH=D:\agentRL\Step-RL`
- 命令：`python -m pytest tests/test_edge_adapters.py -q`
- 期望：5 passed；LocalAdapter 的 observe/execute/catalog/promos/verify 走真实 HTTP/Edge。
- 结果：**PASS（5 passed）**

## ST-02 local reference 零回退

- 命令：
  `python -m pytest tests/test_edge_*.py -q`
- 期望：186 passed。
- 结果：**PASS（186 passed）**

## ST-03 组合回归

- 命令：`python scripts/ar011_eval.py`
- 期望：30/30、policy_steps=0、prompt_tokens=0。
- 结果：**PASS（30/30、0 LLM、0 tokens）**

## ST-04 全量回归（排除既有 gpt2 网络文件）

- 命令：
  `python -m pytest tests -q --ignore=tests/test_progress_estimator.py`
- 期望：260 passed / 3 skipped（已知 10 项 gpt2 代理失败除外）。
- 结果：**PASS（260 passed / 3 skipped）**

## ST-05 安全闸门

- 命令：`python -m pytest tests/test_edge_adapters.py -q`
- 检查：`submit_order` 在 dry-run 下 `PermissionError`；证据写入 password/token/cookie 脱敏；
  限速/页面/金额配置存在。
- 结果：**PASS（单元测试）**

## ST-06 真实 JD 登录闸门（真实失败证据）

- 命令：
  `python scripts/ar029_jd_dryrun.py --query "无线充电器" --headless --max-pages 3`
- 期望（无登录态）：显式 `ok=false`，提示 `--manual-login`，不伪造成功。
- 结果：**PASS（真实拒绝，run_id=20261121_174346_82e811）**

## ST-07 JD 搜索/详情/加购/改量/移除/结算 dry-run

- 前置：用户现场登录并保存 storage_state。
- 命令：
  ```powershell
  $cred="$env:LOCALAPPDATA\StepRL\credentials\jd.json"
  python scripts/ar029_jd_login.py
  python scripts/ar029_jd_dryrun.py --query "无线充电器" --storage-state $cred
  python scripts/ar029_jd_dryrun.py --query "无线充电器" --product "<JD URL>" --storage-state $cred
  python scripts/ar029_jd_dryrun.py --query "无线充电器" --product "<JD URL>" --add-to-cart --storage-state $cred
  python scripts/ar029_jd_dryrun.py --query "无线充电器" --product "<JD URL>" --add-to-cart --cart-quantity 3 --storage-state $cred
  python scripts/ar029_jd_dryrun.py --query "无线充电器" --remove-cart --storage-state $cred
  python scripts/ar029_jd_dryrun.py --query "无线充电器" --product "<JD URL>" --add-to-cart --to-checkout --storage-state $cred
  python scripts/ar029_jd_dryrun.py --query "无线充电器" --orders --storage-state $cred
  ```
- 期望：每类 5 个真实 run；结算页停止，不提交；证据 JSONL/截图/HTML。
- 结果：**BLOCKED（当前环境无法核验；待用户现场登录补跑）**

## ST-08 真实失败/拒绝案例

- 前置：同上。
- 期望：至少 1 个不可行券/无结果搜索/库存不足，显式失败并落证据。
- 结果：**BLOCKED（登录拒绝案例已有；业务失败案例待补跑）**

## ST-09 Gitee 同步与 clone

- 命令：
  `git diff -w --name-status gitee/main main`；全新 `--depth 1` clone 跑 ST-01。
- 期望：diff 为空；clone 中 `tests/test_edge_adapters.py` 5 passed。
- 结果：**PASS（见 tasks T10/T12 记录）**

## 结论

- 框架/local/组合/安全：**PASS**；
- 真实 JD 业务闭环：**BLOCKED**（无伪造）；
- AR029 保持进行中，待 ST-07/ST-08 补跑后再申请最终 Go。
