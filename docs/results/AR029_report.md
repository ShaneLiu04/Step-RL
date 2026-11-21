# AR029 真实多站点适配（第一阶段）状态报告

> 本报告只记录真实执行证据；JD 真实任务需用户现场接管登录，当前尚未补跑，
> 因此不填写任何 JD 成功率。

## 1. 已完成

| 项 | 证据 |
|----|------|
| SiteAdapter 契约 | `step_rl/edge/adapters/base.py` |
| Local reference adapter | `step_rl/edge/adapters/local.py`，真实 LocalShopServer/BrowserEnv |
| JD adapter（dry-run） | `step_rl/edge/adapters/jd.py`，系统 Edge，禁止提交/支付 |
| 证据协议 | `step_rl/edge/adapters/evidence.py`，JSONL/截图/HTML/脱敏 |
| 本地回归 | edge **186 passed**（原 181 + 5 adapter 测试） |
| 组合回归 | AR011 **30/30、0 LLM、0 tokens** |
| 安全闸门 | 1 会话、5s 间隔、20 页面/run、≤200 元、dry-run |

## 2. 已验证的本地 adapter 行为

- `LocalAdapter.reset/observe/execute/catalog/promos/verify` 对真实本地站；
- `goto /cart` 后 page_type=cart；
- 验证器谓词来自真实服务端状态；
- JD helper：搜索 URL、结算 URL、金额解析；
- JD `submit_order` 在 dry-run 下显式 `PermissionError`；
- EvidenceWriter 对 password/token/cookie 脱敏。

## 3. 待补跑（用户接管后）

按用户确认：每类 JD 任务 5 个真实 run，证据落
`outputs/ar029/jd/<run_id>/`：

1. 搜索（无结果搜索也要留证）；
2. 详情（价格/库存）；
3. 加购；
4. 购物车改量/移除；
5. 券可行性（至少 1 个不可行券）；
6. 结算页 dry-run（金额/商品/券信号，不提交）；
7. 订单查询（只读）；
8. 真实失败/拒绝案例（无结果/库存不足/不可行券）。

命令：

```powershell
$env:PYTHONPATH="D:\agentRL\Step-RL"
python scripts/ar029_jd_dryrun.py --query "无线充电器" --manual-login
python scripts/ar029_jd_dryrun.py --query "USB-C" --product "<JD item URL>" `
  --storage-state "$env:LOCALAPPDATA\StepRL\credentials\jd.json" --to-checkout
```

## 4. 未做（明确边界）

- 真实提交订单/支付/取消；
- 淘宝/天猫、Amazon（AR030）；
- Console（AR031）；
- 跨站 baseline/CI（AR032）。

## 5. 真实性声明

- 本地 adapter 测试是真实 HTTP/Edge；
- JD helper/安全测试不联网，不代表 JD 站点成功；
- 未使用 mock 站点或伪造 JD 结果；
- JD 真实证据缺失时，AR029 不能标记为最终验收 PASS。
