# AR029 总纲 Prompt：真实主流电商多站点深度适配 + Agent 前端应用

> 用途：把本文件整段作为新会话的首条 Prompt 交给执行 Agent（OpenCode + HarnessX）。
> 这是一份“总纲/任务书”，不是设计文档。执行 Agent 必须先用 `sdd-router` 进入
> `sdd-task-requirements`，先澄清需求、再设计、再 TDD 开发，禁止直接写代码。

---

## A. 角色与工作方式（给执行 Agent 的硬性指令）

你是 Step-RL 组件工程根目录（`D:\agentRL\Step-RL`）下的 SDD 全流程执行者。
本工作编号 **AR029**，主题 **real-multisite-adaptation**，目录
`specs/changes/AR029-real-multisite-adaptation/`。

你必须：

1. 先加载 `sdd-router`，按状态机进入 `sdd-task-requirements`；
2. 严格执行 HARD-GATE：`srs.md` + `tasks.md` 未经用户确认前，不得生成 `design.md`、不得写任何业务代码；
3. 需求澄清用 `question` 工具分 4 轮（范围→功能→接口→边界），每轮最多 4 个问题；
4. 需求/设计阶段结束后，用 `question` 工具询问用户是否执行阶段门控（`sdd-phase-gate`），PASS 才推进；
5. 开发阶段按 `sdd-task-develop` 的 TDD 纪律：Red → Green → Refactor，覆盖率 ≥80% 语句 / ≥70% 分支；
6. 所有实验结论、成功率、订单号、金额只能来自真实执行日志（见 AGENTS.md 真实性红线）；
7. 任何阶段发现范围膨胀或需求歧义，立即停下问用户，不得自行发明接口或降级为 mock。

本 Prompt 中的“目标/范围/架构/验收”是**需求输入**，最终以用户确认的 `srs.md` 和 `design.md` 为准。

---

## B. 背景与现状（执行前必须核对代码）

当前 Step-RL 的 edge runtime 已在**自建本地商城**上验证了完整能力，但**没有接入任何真实外部站点**：

- 站点与服务端：`step_rl/edge/site.py`（`LocalShopServer`，唯一站点实现）
- 浏览器与观测：`step_rl/edge/browser.py`（`_OBSERVE_JS`，语义元素抽取）
- 验证器：`step_rl/edge/verifier.py`（谓词读取 `/api/state` 与访问路径）
- 规划/目录/券：`step_rl/edge/planner.py`（`fetch_catalog`/`fetch_promos`）
- 技能库/归纳/统计：`step_rl/edge/skill_library.py`、`skill_induction.py`、`skill_stats.py`
- 运行时/事务：`step_rl/edge/runtime.py`（`run_task`、`run_order_sequence`、变换+结算+补偿）
- 并发/缓存：`step_rl/edge/concurrency.py`、`browser.py` 的 `observation_metrics`

已具备的机制（不可回退）：语义观测、验证器 Φ 成功判定、技能编译与 0-LLM 复用、
购物车事务与 Saga 补偿、多订单序列、并发会话隔离、自适应观测缓存、异构布局自适应。

核心缺口：

1. 观测/动作/规划/验证**强耦合**本地站，无法迁移到真实电商；
2. 无登录态、验证码/风控、地址/发票/配送、优惠券叠加、支付等真实链路；
3. 无面向人的**前端 Agent 控制台**（实时画面、人工接管、审批、审计）；
4. 无跨站点评测协议与真实证据矩阵；
5. 现有 demo 只在本地商城，无法证明“真实站点上的优越性与实用性”。

---

## C. 目标（可验证，不是口号）

### G1 站点适配框架
抽象 `SiteAdapter` 契约，把现有 `LocalShopServer` 重构为 **reference adapter**，
且现有 `edge` 测试（181 passed）与 AR011 30/30 零 LLM 全部零回退。

### G2 真实站点深度适配
至少完成 **3 个真实主流电商站点**的端到端适配：

- **必须**：京东（JD）。
- 另选 2 个：优先“境内 1 + 境外 1”，候选：淘宝/天猫、拼多多、苏宁、Amazon、eBay、Walmart。
- “适配”指：真实登录态（人工接管）、搜索、详情、加购、购物车改量/移除、优惠券可行性、
  结算页、提交订单（支付前人工确认）、订单状态查询、取消订单/补偿。

### G3 真实任务闭环
每个站点跑通并留下真实证据的任务矩阵（至少）：
搜索加购、精确改量、批量移除、整体变换、券可行/不可行、单笔下单、多笔订单、
订单查询、取消/补偿、至少 1 个真实失败与恢复案例。

### G4 前端 Agent Console
交付可运行的 Web 前端应用（FastAPI + WebSocket，前端可用 React/Vite 或 Gradio）：

- 站点/账号选择、自然语言任务输入；
- 实时浏览器画面与逐步动作轨迹；
- 验证器证据面板（服务端/订单页权威信号、谓词满足情况）；
- **人工接管**：登录、验证码、支付确认、异常暂停与恢复；
- 订单审计：金额上限、提交前确认、一键取消、完整审计日志；
- 多会话并发看板与运行回放。

### G5 跨站评测与对比
与纯 LLM ReAct baseline 对比，报告每站成功率（验证器口径）、步数、LLM tokens、
端到端时延、费用、失败恢复率、0-LLM 技能复用率、DOM 变更下的鲁棒性；
每任务族样本量 ≥30，给出 95% 置信区间，报告负结果。

### G6 真实证据与可复现
`outputs/ar029/<site>/<run_id>/` 留痕（结构化 JSONL、截图/视频、状态快照、
失败分类、token/费用账本）；提供可复跑脚本、报告、图表、README/REPRODUCTION 更新、
真实多站点演示 MP4。

---

## D. 范围（务实分层，避免一次吞下“全部网站”）

### D1 分层交付

- **Tier A（P1，必须）**：JD，测试账号 + 低价值商品；先做到“提交订单/订单查询/取消”，
  支付默认人工完成。目标：证明真实站点可跑通且有验证器证据。
- **Tier B（P2，选 2）**：境内第二站 + 境外第一站；复用同一任务矩阵与评测协议。
- **Tier C（P3，可选）**：更多站点（Shopee/Temu/Shein 等），只做只读/加购级适配。

### D2 明确 Out of Scope

- 绕过验证码、风控、实名、支付风控；
- 自动免密支付、代付、批量抢购、薅羊毛、刷单；
- 抓取用户隐私/非公开数据、规避站点 ToS；
- 未授权账号、未授权金额、生产环境高价值订单；
- 把站点特判硬编码进 core 模块。

### D3 安全闸门（必须写进 srs/design）

- 默认 **dry-run**（不提交订单）；真实提交需显式开启 + 人工确认；
- 单笔金额上限、单账号频率上限、每站并发上限；
- 提交订单前人工确认；提供一键取消；
- 凭据只存本地 credential store / `storage_state`，禁止写入日志或仓库；
- 验证码/风控命中 → 暂停并转人工，不得绕过。

---

## E. 架构蓝图（设计阶段细化，不在本文件定稿）

### E1 适配器契约
新增 `step_rl/edge/adapters/`：

- `base.py`：`SiteAdapter` Protocol，至少包含
  `name / capabilities / open_session / observe / execute / catalog / promos /
  verify / submit_order / cancel_order / order_status / auth_hooks`。
- `local.py`：包装现有 `LocalShopServer`，作为 golden reference（回归基准）。
- `jd.py`、`taobao.py`、`amazon.py`…：站点实现，不污染 core。

### E2 统一观测与动作
- 观测归一化 schema：`url/title/page_type/elements[]/signals/revision`，
  `element` 含 `role/name/value/state/visible/bbox`；禁止 core 依赖 CSS selector。
- 动作执行器：语义动作 + 可选 selector 回退 + 执行后校验 + 重试/退避 + 幂等键 + 导航守卫。

### E3 验证器
- 共享谓词库 + 每站 adapter 的权威信号映射（订单号、订单列表状态、购物车数量、券 applied）；
- **成功只能由验证器判定**，禁止用模型文本或页面文案“看起来成功”；
- 每个谓词必须可追溯到真实 state/HTTP/DOM 证据。

### E4 规划与技能
- catalog/promo provider 按站点注入；
- 约束可行性（预算/最低价/数量/券门槛）与显式拒绝路径；
- 技能模板站点无关 + 按实时控件能力编译；诱导技能按站点/版本命名空间隔离；
- 失效检测与降级/淘汰（沿用 AR021 统计口径）。

### E5 会话与风控
- 持久化 `storage_state`；人工登录接管；验证码检测暂停；
- 限速、抖动、并发上限、ToS/robots 合规评审记录。

### E6 前端 Console
- 后端 FastAPI + WebSocket；实时画面用 CDP screencast 或限频截图流；
- 人工接管与审批（登录/验证码/支付/取消）；审计日志与证据导出；
- 多会话网格、运行回放、失败原因可视化。

### E7 可观测性
- 每步结构化 JSONL：run_id/site/adapter_version/dom_revision/action/verifier_snapshot/timing/tokens/cost；
- 金额、订单号、券、库存必须来自真实读取。

---

## F. 真实性与安全红线（沿用 AGENTS.md，不可妥协）

- 禁止 mock 站点、随机数、硬编码数组冒充真实结果；
- 失败必须显式返回，禁止静默降级为成功；
- 演示视频必须来自真实会话，订单/金额/状态必须可在服务端或订单页复核；
- 每个站点必须包含至少 1 个真实失败/拒绝/恢复案例，证明不是脚本化 happy path；
- 任何“提升”必须有 baseline 对照与样本量、置信区间；
- 合规文档 `docs/results/AR029_COMPLIANCE.md`：账号来源、授权范围、金额上限、
  频率限制、ToS 结论、支付策略、数据最小化。

---

## G. 评测协议（设计阶段定稿）

- Baseline：
  - B0 纯 LLM ReAct（同模型，无技能/验证器/补偿）；
  - B1 技能 + 验证器（单站）；
  - B2 跨站迁移（同技能/适配器能力迁移）；
  - B3 加事务补偿（失败回滚/取消）。
- 任务集：每站 ≥8 类任务 × ≥5 商品/布局变体，含 held-out 商品与动态价格/库存。
- 指标：verifier success、steps、policy_steps、tokens、latency、费用、recovery、
  0-LLM reuse、DOM churn 下退化、跨站迁移增益。
- 统计：Wilson CI、paired bootstrap；每族 n≥30；报告负结果与失败分类。
- 消融：去验证器 / 去技能 / 去补偿 / 去观测缓存，逐项量化退化。

---

## H. 阶段计划（严格映射 HarnessX）

| 阶段 | Skill | 产物 | 门禁 |
|------|-------|------|------|
| P0 需求 | `sdd-task-requirements` | `srs.md`、`tasks.md` | 用户确认；可选 req gate |
| P1 设计 | `sdd-task-design` | `design.md`、更新 `tasks.md` | 用户确认；可选 design gate |
| P2 开发 | `sdd-task-develop` | 代码 + 测试 + `tasks.md` 状态 | TDD + 覆盖率门禁 |
| P3 审查 | `sdd-task-review` | S/D/C 审查记录 | PASS 才进 ST |
| P4 验收 | `sdd-task-st` | `st-cases.md` + 报告 + 归档 | Go/No-Go |

开发任务草案（需求阶段再细化、可拆子 AR）：

- T01 `SiteAdapter` 契约 + `local` reference + 全量回归零回退
- T02 观测归一化 + 动作执行器 + 验证器谓词框架
- T03 JD 只读适配（搜索/详情/价格/库存）
- T04 JD 购物车（加购/改量/移除）+ 验证器
- T05 JD 结算/券/提交订单（人工确认）/订单查询/取消
- T06 Agent Console MVP（实时画面、轨迹、审批、审计）
- T07 境内第二站适配（同一任务矩阵）
- T08 境外第一站适配（币种/语言/地址/税/配送）
- T09 跨站评测 + baseline 对比 + 失败分类
- T10 真实演示 MP4 + 报告 + 文档 + 归档 + Gitee 同步

> 若一次 AR 过大，需求阶段必须拆分为 AR029（框架+JD）、AR030（第二站）、
> AR031（Console）、AR032（跨站评测），每个子 AR 独立走 SDD 门禁。

---

## I. 交付物清单

- `specs/changes/AR029-real-multisite-adaptation/srs.md`、`design.md`、`tasks.md`、`st-cases.md`
- 适配器与前端代码、测试（含失败注入/恢复用例）
- `outputs/ar029/<site>/<run_id>/` 真实证据
- `scripts/ar029_*.py` 可复跑脚本
- `docs/results/AR029_multisite_report.md` + 图表
- `docs/results/AR029_COMPLIANCE.md`（授权/风控/支付/数据）
- `docs/images/ar029_demo.mp4` + poster（≥3 站点真实运行，含成功与失败）
- README / REPRODUCTION / BACKLOG 更新
- 全新 clone 验证记录

---

## J. 验收标准（Definition of Done）

1. 本地 reference：`edge` 181 passed、AR011 30/30 零 LLM，零回退。
2. JD：≥5 类任务真实跑通，验证器成功率 ≥80%（n≥30 或等价样本），
   订单/取消可在订单页复核；≥1 个失败恢复/拒绝案例；policy_steps=0 的比例达标。
3. 第二/第三站：各 ≥3 类任务跑通，成功率 ≥70%，跨站迁移有对照数据。
4. Console：可现场演示实时画面、人工接管、验证器证据、提交前确认与一键取消、审计导出。
5. 演示：MP4 覆盖 ≥3 站点，屏幕可见真实订单号/金额/验证器结论，且包含失败案例。
6. 所有数字可追溯到 `outputs/ar029/**` 与 `report.json`，无 mock。
7. 合规文档完成且用户确认；无凭据泄露。
8. `git diff -w --stat` 与远端同步无内容差异（按 AGENTS.md Gitee 流程）。

---

## K. 风险与预案

| 风险 | 预案 |
|------|------|
| 登录/验证码/风控 | 人工接管、低频、测试账号；不绕过，必要时降级只读 |
| DOM 频繁变更 | 语义观测 + 运行时修复 + 失效检测 + 快速淘汰 |
| 价格/库存/地域差异 | 实时读取 + 预检拒绝，不猜测 |
| 封号/反爬 | 限速、并发上限、可暂停；优先官方 API/沙箱 |
| 支付合规 | 默认人工支付；提交订单人工确认；金额上限 |
| ToS/法律 | 先合规评审，仅授权测试；保留结论文档 |
| 范围失控 | Tier 化，P1 JD 优先；大 AR 拆子 AR |

---

## L. 反模式（出现任一条即视为方案不通过）

- 用本地/mock 站点冒充真实站点；
- 用 demo 脚本硬编码“成功”；
- 绕过验证码/风控或自动免密支付；
- 只做 happy path，不做失败/拒绝/恢复；
- 不做 baseline 对照与样本量/置信区间；
- 把单站结论说成通用；
- 在 core 模块写站点特判；
- 未确认需求就生成 design 或写代码。

---

## M. 启动指令（把下面这段作为新会话第一条消息）

```
加载 sdd-router，处理 AR029（real-multisite-adaptation）。
严格按 skill 执行：先建立领域知识，再用 question 工具分 4 轮做需求澄清
（范围→功能→接口→边界，每轮≤4 问），然后生成 srs.md + tasks.md 并暂停等我确认。
不要直接写 design.md，不要写业务代码。
需求输入见 specs/changes/AR029-real-multisite-adaptation/PROMPT.md。
重点：真实主流电商（JD 必须 + 另选 2 站）深度适配、Agent 前端控制台、
真实证据与跨站 baseline 评测；禁止 mock、禁止绕过风控、禁止自动支付。
```

---

## N. 备注

- 本文件只定义“要什么、为什么、怎么验收”，不定义最终接口与算法；接口由 `design.md` 定稿。
- “接入全部主流网站”不是单个 AR 的合理边界。正确做法是：先把**适配器框架 + JD**
  做成可复用的证据闭环，再按 Tier 增量复制，避免把一次性脚本说成通用架构。
