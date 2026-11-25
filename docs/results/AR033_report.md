# AR033 混合系统级验证报告（真实 CPU/GPU）

> 目标：验证“确定性层 + 端侧 LLM + 人工/证据层”能否作为一个系统闭环运行。
> 所有数字来自真实 LocalShopServer/Edge/模型；远程只读结果不伪造成功率。

## 1. CPU 确定性层

| 指标 | 结果 |
|------|------|
| AR011 30 场景 | **30/30** |
| policy steps / prompt tokens | **0 / 0** |
| 技能步数 | 276 |
| 总耗时 | 82.86s |

## 2. GPU 端侧 LLM 兜底层

| 指标 | 结果 |
|------|------|
| 任务 | “把购物车中的无线充电器移除” |
| 结果 | **成功** |
| 路径 | skill 缺失 → LLM fallback |
| policy steps / prompt tokens | 4 / 1142 |
| 耗时 | 28.58s（含模型生成） |
| 模型 | `~/.cache/huggingface/hub/models--Qwen--Qwen3-0.6B-Base/snapshots/main` |
| 最终 cart | `{}` |

说明：该任务不是硬编码成功；确定性技能没有 remove 模板，真实调用端侧 Qwen 兜底，
验证器确认购物车为空。

## 3. Console / 证据层

| 项 | 结果 |
|----|------|
| Console local 会话 | success |
| 截图 | 有 |
| 事件 | 6 |
| 审计目录 | `outputs/ar031/sessions/<id>/` |

## 4. 远程只读（真实失败隔离）

| 站点 | 结果 |
|------|------|
| JD | 搜索页打开但触发“访问频繁/无法搜索”风控 → 失败 |
| Taobao | 空标题/反爬 → 失败 |
| 单站异常 | `HybridSystem` 捕获并返回 `ok=false`，不中断 CPU/GPU/Console |
| Amazon | 搜索页真实加载 → 只读成功 |

单站失败被 `HybridSystem` 捕获，不会中断 CPU/GPU/Console 其他层。

## 5. 结论

- **系统级闭环成立**：CPU 30/30、GPU 兜底成功、Console 可运行、证据落盘；
- **端侧 LLM 的价值被实测**：未覆盖的 remove 由 LLM 完成，4 步/1142 tokens；
- **真实多站业务仍受站点访问/账号/反爬限制**，这不是模型能力本身；
- 正确路线是：确定性 adapter/verifier 优先，LLM 兜底，人工接管，证据层审计。

## 6. 复现

```powershell
$env:PYTHONPATH="D:\agentRL\Step-RL"
python scripts/ar011_eval.py
python scripts/ar033_system_eval.py
python -m pytest tests/test_hybrid_system.py tests/test_console.py -q
```

原始数据：`outputs/ar033/eval/ar033_results.json`、`outputs/ar011/`、`outputs/ar031/`。
