# [AR029] 任务跟踪

| 字段 | 内容 |
|------|------|
| AR 编号 | AR029 |
| 主题 | real-multisite-adaptation |
| 关联 srs.md | ./srs.md |
| 关联 design.md | ./design.md（已生成） |
| 创建日期 | 2026-11-21 |
| 状态 | 开发中（JD 真实证据待补跑） |

## 阶段拆分（用户已确认）

| AR | 内容 | 状态 |
|----|------|------|
| AR029 | SiteAdapter 框架 + local reference + JD dry-run | 开发中 |
| AR030 | 淘宝/天猫 + Amazon（先只读） | 未开始 |
| AR031 | Agent Console（实时画面/接管/审批/审计） | 未开始 |
| AR032 | 跨站评测 + baseline + CI + MP4 | 未开始 |

## 任务列表

| ID | 任务描述 | 依赖 | 状态 | 备注 |
|----|----------|------|------|------|
| T01 | `SiteAdapter` Protocol + `adapters/local.py` reference，core 回归零回退 | - | passing | local golden 对照 |
| T02 | 统一观测 schema + 动作执行协议（core 不依赖 CSS） | T01 | passing | local 逐字段一致 |
| T03 | 验证器适配层：站点权威信号 → 共享谓词 | T01/T02 | passing | 成功只由验证器 |
| T04 | JD 只读：搜索/详情/价格/库存/订单查询 | T02/T03 | in_progress | 真实 JD/Edge |
| T05 | JD 购物车：加购/改量/移除 + 验证器 | T04 | in_progress | 真实页面操作 |
| T06 | JD 券可行性 + 结算页 dry-run（金额/商品信号） | T04/T05 | in_progress | 不提交订单 |
| T07 | 登录/验证码人工接管钩子 + 本地 credentials/storage_state | T04 | passing | 不入仓/日志 |
| T08 | 真实证据协议：JSONL/截图/HTML/验证器快照 + 失败分类 | T05/T06 | passing | `outputs/ar029/jd` |
| T09 | JD dry-run 任务矩阵与失败/拒绝样例（每类 5 run，待用户接管补跑） | T08 | in_progress | 已获得真实登录拒绝案例；成功任务待补 |
| T10 | 合规文档 + README/REPRODUCTION + Gitee 同步 + clone 校验 | T09 | passing | `main=fc79562`；clone adapter 5 passed |

## 状态说明

- `pending`：待开始
- `in_progress`：进行中
- `passing`：测试/证据通过
- `failed`：失败待修复

## 进度记录

- 2026-11-21：完成 4 轮需求澄清；用户确认 AR029–AR032 拆分、JD dry-run、
  Console 延后、1 会话/5s/20 页面/≤200 元、每类 5 run、证据 JSONL+截图+HTML。
- srs/design 已确认，按自动闭环推进。
- 2026-11-21：LocalAdapter/证据协议/JD dry-run adapter 代码完成；edge **186 passed**（181+5）、AR011 **30/30、0 LLM**；真实 JD 证据待用户现场接管补跑。
- Gitee 同步完成；全新 clone `tests/test_edge_adapters.py` **5 passed**；AR029 仍为“进行中”。
- 2026-11-21 深度闭环：真实 JD 只读被登录闸门拦截（ok=false），修复导航观测重试与 host 误判；真实成功证据待 `--manual-login` 补跑。全量（排除 gpt2）**260 passed / 3 skipped**。

## 阶段门控记录

- 2026-11-21：用户确认 srs/tasks 并要求自动闭环；按自动模式跳过人工门控询问，进入设计/开发。