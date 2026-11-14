# [AR022] 订单状态查询技能（order status query）需求设计说明书

## 1. 背景与目标

AR016/AR017/AR019 已覆盖下单、多订单组合、Saga 补偿与技能归纳闭环，
技能库也覆盖了搜索/加购/更新/结算/移除等购物车侧操作；但用户侧高频的
**订单状态查询**（「查询我最近的订单状态」「查看我最近取消的订单状态」）
没有任何对应能力。改动前基线探针（`scripts/ar022_baseline_probe.py`，
旧代码真实执行，`outputs/ar022/baseline_probe.json`）暴露三处真实缺陷：

1. **规划器不支持**：`plan_instruction("查询我最近的订单状态")` 返回
   `None`（planner_unsupported），组合运行时直接显式失败
   （`fallback_required=True`）；
2. **站点没有订单列表页**：真实 HTTP 请求 `/orders` 返回 404「页面不存在」，
   订单信息只能通过结算成功后的 `/order/{id}` 单页看到（且无状态字段），
   下单后无法再回头查看订单状态；
3. **技能注册表无对应操作**：不存在 `order_query` 操作的能力门控/技能路径，
   即使 LLM 偶然完成一次，轨迹也无归纳落点（AR019 闭环接不住）。

目标（BACKLOG B04）：让「查询订单状态」成为一个**真实可验证、可 0-LLM
复用**的技能——新增真实订单列表页（服务端真实订单状态：有效/已取消），
规划器编译该指令，验证器提供真实订单页谓词，AR019 归纳闭环在真实 LLM
兜底成功后把查询轨迹沉淀为技能；此后同类指令 **3/3、0 LLM**。

## 2. 范围

- `step_rl/edge/site.py`：`/orders` 订单列表页（真实服务端订单状态渲染）
  + v1/v2 头部「我的订单」入口（**纯增量**：新路由 + 头部新增一个链接，
  既有页面语义不变）；
- `step_rl/edge/planner.py`：「查询/查看 + 订单」→ `order_query` TaskSpec；
- `step_rl/edge/verifier.py`：`orders_viewed` / `latest_order_active` /
  `latest_order_cancelled` 三个真实状态谓词；
- `step_rl/edge/policy.py`：`PREDICATE_HINTS` 增加对应中文提示；
- `step_rl/edge/skill_library.py` / `capability.py` / `runtime.py`：
  **零代码改动**（见 design D5：现有「归纳注册表 + 统计 + 选择 + 显式
  缺口」机制对 `order_query` 操作天然成立）；
- 评测 `scripts/ar022_eval.py`（真实 Edge / GPU / 服务端状态）与改动前
  基线探针 `scripts/ar022_baseline_probe.py`（改动前在旧代码上执行）；
- 单测 `tests/test_edge_order_query.py`；
- 不在范围：v3 布局（B06）、并发隔离（B07）、观测缓存（B08）、优惠券
  约束（B05）、B03 剩余的长度平局裁决、订单历史分页/详情编辑；
  不训练新模型；不修改 AR001–AR021 已归档内容。

## 3. 功能需求

### FR1 站点订单列表页（`site.py`）

- 新路由 `GET /orders`：按最新在前列出真实订单（订单号、商品明细、
  状态），状态为服务端权威值 `active`/`cancelled`，页面文案「有效 /
  已取消」；空列表显示「暂无订单」；
- v1 头部新增 `<a id='nav-orders' href='/orders'>我的订单</a>`；v2 头部
  新增 `<a id='orders-link-2' href='/orders' aria-label='我的订单'>我的订单</a>`
  ——两套布局 **accessible name 相同**（语义层跨布局迁移前提，AR005 标准）；
- 既有路由（`/`、`/search`、`/product/`、`/add/`、`/cart`、`/checkout`、
  `/order/{id}`、`/cancel/`、`/api/*`）行为逐字段不变。

### FR2 规划器 `order_query` 分支（`planner.py`）

- 门控关键词新增「查询」「查看」；
- 分支条件：指令含「查询」或「查看」**且**含「订单」→
  `TaskSpec(task_id="planned_order_query", level=2, operation="order_query",
  targets={}, start_path="/", predicates=[...])`；
- 谓词选择：指令含「取消」→ `["orders_viewed", "latest_order_cancelled"]`；
  否则 `["orders_viewed", "latest_order_active"]`；
- 回归保护：结算类指令（含「结算/下单/提交订单」）不得落入本分支
  （「完成结算并提交订单」仍走 checkout 路径）；既有指令的规划结果不变。

### FR3 验证器真实订单页谓词（`verifier.py`）

- `orders_viewed`：`visited` 含 `/orders`（真实访问日志）；
- `latest_order_active`：服务端 `orders` 非空且
  `orders[-1]["status"] == "active"`；
- `latest_order_cancelled`：服务端 `orders` 非空且
  `orders[-1]["status"] == "cancelled"`；
- 全部读取真实服务端状态（`/api/state`），不信任页面文本与模型自述。

### FR4 归纳与复用（零代码改动）

- 未注册时：`skill_for_subtask` 对 `order_query` 返回 `None` → 能力门控
  显式缺口 `no_skill_for_level_2`（AR019 语义）；
- 真实 LLM 兜底（GPU，AR004 适配器）成功后，`induce_skill` 把轨迹泛化为
  模板（本场景无 `{product}` 占位符：`goto` 保持 URL、`click` 保持
  accessible name）→ `register_induced_skill("order_query", ...)` →
  门控翻转 covered；
- AR021 统计/优先级/淘汰机制对 `order_query` 自动生效（同名再注册重置
  统计、失败让位、显式缺口自愈）。

### FR5 评测（`scripts/ar022_eval.py`）

真实 Edge（Playwright `channel=msedge`）+ 真实服务端状态 + 真实 GPU LLM
兜底（AR004 三个适配器路径），阶段 P0–P5：

| 阶段 | 内容 |
|------|------|
| P0 | 改动后复核：规划器编译两条指令（active/cancelled 谓词）、`/orders` 真实 200 且渲染真实订单、v1/v2 头部入口存在、门控注册前 `no_skill_for_level_2` / 注册后 covered（真实规划器，无 GPU） |
| P1 | 真实下单（编译技能，0 LLM）→ 同会话真实 LLM 兜底执行「查询我最近的订单状态」（GPU，沉淀成本：步数/prompt tokens）→ 成功且订单状态 active |
| P2 | 归纳：`TrajectoryRecorder` 轨迹 → `induce_skill` → 注册 `induced_order_query` → 持久化 induced_skills.json → 门控翻转 covered |
| P3 | 技能路径 0 LLM 三场景：**3/3**——R1 同会话查询（active）；R2 真实 `/cancel/` 后查询（cancelled 谓词）；R3 v2 布局 + 全量 ID churn 新会话（新真实订单） |
| P4 | 效率对照：LLM 兜底（P1）vs 技能复用（P3）的 LLM 调用 / prompt tokens / 耗时 |
| P5 | 组合门禁：edge pytest 套件（179 基线 + 新增全过）+ AR011 30 场景（30/30、0 LLM） |

### FR6 文档

README 5.x 新章节（插入 EX001 之前，EX001 顺延编号）、5.1 结果表、
5.6 回退记录、AR 演进表、版本表、快速开始、目录树、徽章；
`docs/REPRODUCTION.md` 复现命令；BACKLOG B04 毕业记录。

## 4. 非功能

- 既有 179 项 edge 测试不得回退（AR019/AR020/AR021 全绿为硬约束）；
- 站点改动纯增量：既有 30 场景统一套件的 DOM 语义不变（头部多一个链接，
  技能按名称匹配不受影响）；
- 不新增依赖、不训练新模型；所有指标来自真实执行日志
  （`outputs/ar022/**`），禁止 mock / 硬编码。

## 5. 假设

- 0.6B 语义适配器（AR004 路径）能依据验证器提示与头部「我的订单」
  可交互元素完成一次真实点击——若兜底失败按组合回退规则诚实记录
  （负结果归档），不伪造归纳；
- 单卡 GPU（Quadro RTX 5000 16GB）可跑 AR004 适配器（既有 AR 已验证）；
- 「订单状态查询」的用户指令形态为「查询/查看 … 订单 … 状态」，
  规划器做确定性编译，不引入语言模型猜测。

## 6. 术语

- 订单列表页（`/orders`）：新增真实路由，渲染服务端权威订单与状态；
- `order_query` 操作：规划器编译出的新操作类型，targets 为空、
  以真实订单页谓词判定成功；
- 沉淀成本：LLM 兜底成功一次的步数与 prompt tokens（AR019 语义）；
- 状态谓词：读取服务端 `orders[-1].status` 的真实判定（有效/已取消）。
