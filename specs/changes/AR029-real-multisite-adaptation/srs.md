# [AR029] 真实主流电商多站点深度适配（第一阶段：框架 + JD dry-run）需求设计说明书

| 字段 | 内容 |
|------|------|
| AR 编号 | AR029 |
| AR 主题 | real-multisite-adaptation |
| 阶段 | 第一阶段（框架 + local reference + JD dry-run） |
| 日期 | 2026-11-21 |
| 状态 | Draft（待用户确认） |
| 上游输入 | `specs/changes/AR029-real-multisite-adaptation/PROMPT.md` |

## 1. 背景与目标

当前 Step-RL edge 运行时只在自建 `LocalShopServer` 上验证：语义观测、验证器 Φ、
技能编译/归纳、购物车事务、Saga 补偿、并发隔离、观测缓存均已成立，但观测/动作/
验证强耦合本地站，无法迁移到真实电商，也没有面向人的控制台与跨站证据。

AR029 只解决“可迁移的适配器骨架 + 第一个真实站点（JD）的安全 dry-run 闭环”。
完整多站点、Console、跨站 baseline 评测按用户确认拆到 AR030–AR032，避免单 AR 失控。

**AR029 目标：**
1. 抽出 `SiteAdapter` 契约，把 `LocalShopServer` 包成 reference adapter；
2. 现有 edge 测试（181 passed）与 AR011 30/30 零 LLM 零回退；
3. 提供 JD adapter 的真实页面适配与 dry-run 任务矩阵；
4. 建立真实证据协议（JSONL/截图/HTML/验证器快照），供后续有人值守实验补跑；
5. 明确安全闸门与合规边界，禁止自动支付/绕过风控/mock。

## 2. 范围

### 2.1 In Scope（AR029）

- `step_rl/edge/adapters/`：`SiteAdapter` Protocol、`local` reference adapter；
- 统一观测 schema 与动作执行协议（core 不依赖站点 CSS selector）；
- 验证器适配层：站点权威信号 → 共享谓词；
- JD adapter：
  - 真实搜索、详情、价格/库存读取；
  - 加购、购物车改量/移除（真实页面操作）；
  - 优惠券可行性读取（只读判断）；
  - 结算页到达与表单/金额读取（dry-run，不提交订单）；
  - 订单查询（只读）；
  - 登录/验证码人工接管钩子；
- JD dry-run 任务矩阵与 5 类失败/拒绝样例设计（不可行券、无结果搜索、库存不足等）；
- 真实证据协议：`outputs/ar029/jd/<run_id>/` JSONL、截图、HTML 快照、验证器快照；
- 本地回归：edge 181 + AR011 30/30；
- 文档：README/REPRODUCTION 更新、`docs/results/AR029_COMPLIANCE.md`；
- Gitee 同步与全新 clone 校验。

### 2.2 Out of Scope（AR029，后续 AR）

- AR030：淘宝/天猫、Amazon 适配；
- AR031：Agent Console（实时画面、人工接管 UI、审批/审计）；
- AR032：跨站 ≥30 样本/任务族、baseline 对比、置信区间、MP4 演示；
- 自动提交真实订单、自动支付、取消真实订单；
- 绕过验证码/风控/实名；高价值订单；
- 把 JD 特判写进 core 模块。

## 3. 用户确认的关键决策

| 决策 | 结果 |
|------|------|
| AR 拆分 | AR029 框架+JD；AR030 第二/三站；AR031 Console；AR032 跨站评测 |
| 站点规划 | 京东 + 淘宝/天猫 + Amazon（后两站 AR030，先只读） |
| 账号 | 仅 JD 有测试账号；其他站暂无 |
| JD 链路 | 到**结算页 dry-run**，不提交订单 |
| 人工接管 | 用户可现场完成登录/验证码/确认 |
| 实验时点 | 本轮先交付代码/测试；真实 JD 证据待用户接管后补跑 |
| 安全策略 | 默认 dry-run；1 会话；动作间隔≥5s；每轮≤20 页面；单笔≤200 元 |
| 商品 | 低价值 3C 配件 |
| 证据 | JSONL + 截图 + HTML 快照 |
| 失败案例 | 不可行券 / 无结果搜索 / 库存不足（不产生订单） |
| 样本 | 每类 5 个真实 run；n≥30 与 CI 放 AR032 |

## 4. 功能需求

### FR1 SiteAdapter 契约与 local reference
- 定义站点无关契约：`name / capabilities / open_session / observe / execute /
  catalog / promos / verify / order_status / auth_hooks`；
- `local` adapter 包装现有 `LocalShopServer`，行为与当前 edge 运行时逐字段一致；
- core（planner/runtime/verifier）通过 adapter 能力工作，不新增站点特判。

**验收：** edge 181 passed；AR011 30/30、0 LLM；local adapter 与旧路径结果一致。

### FR2 统一观测与动作
- 归一化观测：`url/title/page_type/elements[]/signals/revision`；
- 元素包含 `role/name/value/state/visible`（bbox 可选）；core 不依赖 CSS selector；
- 动作执行：语义动作、执行后校验、失败显式返回、导航守卫；
- JD adapter 可注入站点特定 DOM 解析，但不得污染 core。

**验收：** local golden 测试逐字段一致；JD 观测可被同一 schema 消费。

### FR3 验证器适配
- 共享谓词库 + 每站权威信号映射（订单号、订单状态、购物车数量、券 applied、
  结算页金额/商品）；
- 成功只能由验证器判定，禁止用页面文案/模型文本“看起来成功”；
- JD dry-run 的“成功”= 到达真实结算页且金额/商品/券信号可追溯，不提交订单。

**验收：** 失败/拒绝路径显式；每个谓词有真实 DOM/HTTP 证据。

### FR4 JD 适配（dry-run）
- 真实 JD 页面：搜索、详情、加购、购物车改量/移除、券可行性、结算页；
- 商品/价格为实时读取；不可行券/库存不足/无结果必须显式拒绝；
- 需要登录时暂停并转人工；验证码/风控命中必须暂停，不绕过；
- 不点击提交订单、不自动支付。

**验收：** 用户接管后，每类任务 5 个真实 run；至少 1 个真实失败/拒绝案例；
所有证据可追溯到 `outputs/ar029/jd/<run_id>/`。

### FR5 会话与安全
- 登录态放本地 credentials 目录（不入仓/日志）；
- 1 会话、动作间隔≥5s、每轮≤20 页面、单笔金额≤200 元；
- 默认 dry-run；真实提交需显式开关 + 人工确认（AR029 不使用提交）；
- 凭据/PII 不写入日志；截图需脱敏/最小化。

### FR6 证据与可复现
- 每步 JSONL：run_id/site/adapter_version/url/action/verifier/timing/信号；
- 关键页面截图与 HTML 快照；
- 失败分类与拒绝原因；
- 不包含账号密码、Cookie 明文、支付信息。

### FR7 合规
- `docs/results/AR029_COMPLIANCE.md`：账号来源/授权范围/金额上限/频率限制/
  ToS 结论/支付策略/数据最小化。

## 5. 非功能需求

| 类型 | 要求 |
|------|------|
| 真实性 | 真实 JD/Edge；禁止 mock/随机数/硬编码成功 |
| 安全 | dry-run、人工接管、限速、无自动支付、凭据不入仓 |
| 兼容 | local 零回退；core 保持站点无关 |
| 可复现 | 固定命令、run_id、证据目录、README/REPRODUCTION |
| 可观测 | 每步动作/验证器/金额/失败原因可审计 |

## 6. 约束与假设

- AR029 不验收真实订单提交/取消；该链路留到有人值守的后续 AR；
- 其他站点无账号，AR030 先只读；
- JD 页面 DOM/风控会变化，适配必须可失效显式失败；
- 用户需在真实 JD 实验时现场接管；
- 样本 n=5/类仅用于 AR029 可运行性；统计显著性在 AR032。

## 7. 交付物

- `srs.md`、`design.md`、`tasks.md`、`st-cases.md`；
- `step_rl/edge/adapters/`（base/local/jd）；
- 测试（local golden + JD dry-run/失败/拒绝）；
- `outputs/ar029/jd/<run_id>/` 证据（用户接管后补跑）；
- `scripts/ar029_*.py`；
- `docs/results/AR029_COMPLIANCE.md`、`docs/results/AR029_report.md`；
- README/REPRODUCTION/BACKLOG 更新；
- Gitee 同步 + 全新 clone 校验。

## 8. 验收标准（AR029）

1. local reference：edge **181 passed**、AR011 **30/30、0 LLM** 零回退；
2. JD adapter 代码 + dry-run 测试通过；用户接管后每类 5 个真实 run（可后续补跑）；
3. 至少 1 个真实失败/拒绝（不可行券/无结果/库存不足）且显式记录；
4. 证据目录、JSONL、截图、HTML、验证器快照完整；无凭据/PII 泄漏；
5. 合规文档完成；
6. Gitee 内容 diff 为空，全新 clone 可复现。

## 9. 风险与预案

| 风险 | 预案 |
|------|------|
| JD 登录/验证码/风控 | 人工接管、低频、测试账号；命中即暂停 |
| DOM 变更 | adapter 内解析、显式失败、快速淘汰 |
| 账号/金额风险 | dry-run、≤200、1 会话、5s 间隔 |
| 范围膨胀 | 严格 AR029–032 分层；Console/跨站不做 |
| 无真实账号时无法验收 | 代码/测试先交付，真实证据待用户接管补跑 |
