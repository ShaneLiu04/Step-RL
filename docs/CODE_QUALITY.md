# Step-RL 代码质量审查记录（AR029–AR033）

> 目标：在新增多站适配/Console/混合系统后，做一次可执行的代码质量闭环；
> 不改变已验证行为，不引入 mock。

## 1. 审查范围

- `step_rl/edge/adapters/*`（base/local/jd/remote/taobao/amazon/evidence）
- `step_rl/system.py`
- `step_rl/console/*`
- `scripts/ar029_*`、`ar032_*`、`ar033_*`
- 新增测试 `test_edge_adapters.py`、`test_edge_remote_adapters.py`、`test_console.py`、`test_hybrid_system.py`

## 2. 静态检查

```powershell
python -m compileall -q step_rl\edgedapters step_rl\console step_rl\system.py
python -m ruff check <上述目录/文件> --select F,E9
```

结果：**compileall 通过；F/E9 All checks passed**。

> Ruff 默认全规则会报大量历史 `Dict/List` 注解与宽异常风格问题；本轮只修复
> 真实功能/可维护性问题，避免大规模风格改动引入回归。

## 3. 发现与修复

| # | 问题 | 修复 |
|---|------|------|
| 1 | `system.py` 未使用变量 `writer` | 删除 |
| 2 | `evidence.py` 未使用 `Iterable` 导入 | 删除 |
| 3 | `remote.py`/`jd.py` 重复调用 `page.title()` | 缓存一次 title |
| 4 | 远程单站超时曾中断整个系统 | `HybridSystem.run_remote` 隔离异常，返回 `ok=false` |
| 5 | JD 导航中观测 `Execution context destroyed` | 增加观测重试与页面稳定等待 |
| 6 | JD 登录页 host 误判 | 按 host 判定，登录页优先 |
| 7 | 风控页被当普通空结果 | 识别“访问频繁/无法搜索/验证码”为 `risk_control` |
| 8 | Console 真实 session 测试用 TestClient 后台任务挂起 | 改为直接 `SessionManager` + `asyncio.run` |
| 9 | 多行购物车同 selector 丢元素 | 观测按 DOM 节点去重（AR027） |

## 4. 测试

- Adapter/Console/Hybrid 针对性测试：**13 passed**
- 全量（排除既有 gpt2 网络文件）：**268 passed / 3 skipped**
- edge：**186 passed**

## 5. 结构评价

### 优点
- adapter 边界清晰：站点特判只在 `adapters/*`，core 不依赖 JD/淘宝选择器；
- 失败显式：登录/风控/空标题/无商品链接都不伪装成功；
- 证据可审计：JSONL/截图/HTML/脱敏；
- LLM 与确定性层分离：技能优先，LLM 仅兜底；
- Console/系统入口复用同一 runtime，避免两套执行逻辑。

### 仍存技术债
1. `jd.py`/`remote.py` 生命周期/限速/截图有重复，可抽 `BrowserSessionBase`；
2. 部分异常为宽 `except Exception`，用于清理/隔离，后续应加结构化日志；
3. 远程 selector 仍是站点特定，需持续用真实页面回归；
4. Console 暂停/审批 API 已有状态，但尚未与每个动作级 hook 完全联动；
5. 跨站 CI/n≥30 仍缺账号与样本；
6. 全量并发运行时观察到 1 次 AR028 preflight 瞬时失败，单独复跑与全量重跑均通过；
   后续可加浏览器夹具隔离/有限重试，区分环境抖动与真实回归。

## 6. 结论

- 代码质量在本轮达到“可运行、可测试、可审计”的工程闭环；
- 不把未验证的远程业务写成成功；
- 下一阶段优先：抽公共 BrowserSessionBase、补真实账号任务矩阵、Console
  动作级审批钩子。


## 7. 第二轮全仓静态优化（2026-11-21）

对 `step_rl/ scripts/ tests/` 执行：

```powershell
python -m ruff check step_rl scripts tests --select F,E9
# All checks passed!
```

修复内容：

- **真实 bug**：`scripts/ar005_eval.py` 循环解包缺少 `perturb`，且使用未定义变量；
  已改为 5 元组解包并传入 `perturb`；
- `scripts/ar018_eval.py` / `ar019_eval.py` / `ar021_baseline_probe.py` 未使用变量；
- 25 个未使用导入 / 无占位 f-string 自动清理；
- 全仓 F/E9 由 31 条降为 **0**；
- 全量回归 **268 passed / 3 skipped**（排除既有 gpt2 网络文件）。

> 仍保留历史 `Dict/List` 注解、宽异常清理等风格债务；本轮不盲目批量改风格，
> 以避免改变已验证行为。后续可单独做“类型注解现代化”与“结构化日志”专项。


## 8. 第三轮：封装/脱敏与可重复门禁（2026-11-21）

### 修复
- 新增 `BrowserEnv.screenshot()`，`system/console` 不再直接访问 `_page` 私有成员；
- EvidenceWriter 脱敏扩展到 JD `pt_key/pt_pin/thor/wskey`；
- 新增 `scripts/code_quality.py` 一键门禁。

### 门禁命令与结果

```powershell
$env:PYTHONPATH="D:gentRL\Step-RL"
python scripts/code_quality.py --full
```

结果：
- compileall rc=0；
- ruff F/E9 `All checks passed`；
- 关键 adapter/console/system 测试 **16 passed**；
- 全量（排除既有 gpt2）**271 passed / 3 skipped**；
- 门禁汇总 `{failed: [], ok: True}`。

### 结论
代码质量已从“一次性人工检查”变为可重复门禁；未验证的远程业务仍不写成成功。
