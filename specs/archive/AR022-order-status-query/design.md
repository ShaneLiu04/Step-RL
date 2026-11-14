# [AR022] 增量实现设计

## 1. 总体思路

「订单状态查询」从**完全不支持**（规划器 `None`、站点 404、无技能落点）
升级为**规划器编译 → 真实订单页谓词 → 归纳技能 0-LLM 复用**。核心不变式：
**成功判定只认服务端真实状态**（`orders[-1].status` 与真实访问日志），
**站点改动纯增量**（新路由 + 头部一个链接，既有路由逐字段不变），
**技能库/门控/运行时零代码改动**（`order_query` 走既有通用机制）。

```
「查询我最近的订单状态」
  └─ plan_instruction：(查询|查看) 且 订单 → TaskSpec(order_query)
  └─ check_capability：skill_for_subtask → None（未注册）
       └─ 显式缺口 no_skill_for_level_2（AR019 语义）
  └─ run_skill_hierarchy(fallback=True, reset=False)：真实 LLM 兜底（GPU）
       └─ TrajectoryRecorder 记录真实执行
  └─ induce_skill → register_induced_skill("order_query", ...)
       └─ 门控翻转 covered；此后同类指令走技能路径：0 LLM
  └─ 验证器：orders_viewed（真实 visited）
       + latest_order_active / latest_order_cancelled（真实 orders[-1].status）
```

## 2. 模块改动

### 2.1 `site.py`（纯增量）

- `_page` 头部：v1 在「购物车」链接后插入
  `<a id='nav-orders' href='/orders'>我的订单</a>`；v2 对应插入
  `<a id='orders-link-2' href='/orders' aria-label='我的订单'>我的订单</a>`；
- 新 `render_orders(state, layout)`：最新订单在前，每单一张卡
  （订单号 + 商品明细 + 状态 pill：`active`→「有效」、`cancelled`→「已取消」），
  空列表「暂无订单」；
- `_Handler.do_GET` 新增 `elif path == "/orders"` 分支（置于 404 兜底前）。

### 2.2 `planner.py`

- 门控元组新增「查询」「查看」；
- 新分支（位于「缺货替代」之后、「mentions 通用路径」之前）：

```python
if any(w in instruction for w in ("查询", "查看")) and "订单" in instruction:
    preds = ["orders_viewed"]
    preds.append("latest_order_cancelled" if "取消" in instruction else "latest_order_active")
    return TaskSpec(
        task_id="planned_order_query", level=2, goal=instruction,
        search_query="", targets={}, require_checkout=False,
        operation="order_query", predicates=preds, start_path="/",
    )
```

### 2.3 `verifier.py`

`_predicates` 新增（均读真实服务端状态）：

```python
def orders_viewed(state, url):  return _visited(state, _path_is("/orders"))
def latest_order_active(state, url):
    history = state.get("orders") or []
    return bool(history) and history[-1].get("status") == "active"
def latest_order_cancelled(state, url):
    history = state.get("orders") or []
    return bool(history) and history[-1].get("status") == "cancelled"
```

### 2.4 `policy.py`

`PREDICATE_HINTS` 增加：`orders_viewed`→「打开订单列表页」、
`latest_order_active`→「最近订单为有效状态」、
`latest_order_cancelled`→「最近订单为已取消状态」。

### 2.5 `skill_library.py` / `capability.py` / `runtime.py`（零改动）

- 未注册：`skill_for_subtask` 中 `task.operation not in ("add","")` →
  `None` → 门控 `no_skill_for_level_2`（既有显式缺口路径）；
- 已注册：`task.operation in _INDUCED` → `_select_best` →
  `_materialize`；本场景 targets 为空，走 `_materialize` 的
  `if not pids:` 分支（逐步入例化、无占位符替换）；
- 成败记录：`run_skill_hierarchy` 既有的 `record_skill_outcome` 钩子自动
  覆盖 `order_query`（AR021 机制，验证器确认口径）。

### 2.6 `scripts/ar022_baseline_probe.py`（改动前执行，旧代码留证）

探针（全部真实执行，旧代码）：

- A 规划器缺口：`plan_instruction("查询我最近的订单状态")` → `None`；
  `check_capability` → `planner_unsupported`；
- B 站点 404：真实 HTTP `GET /orders` → 404「页面不存在」；
- C 无技能落点：注册表中无 `order_query` 操作（`induced_operations()`
  不含它）；结算成功页 `/order/{id}` 无状态字段（真实 GET 后页面文本
  不含「有效/已取消」）。

输出 `outputs/ar022/baseline_probe.json` + `baseline_probe.md`。

### 2.7 `scripts/ar022_eval.py`（改动后主评测）

结构对齐 AR020/AR021：`set_seed(42)`；P0–P5；每阶段 JSON 落盘
`outputs/ar022/eval/ar022_results.json` + `ar022_report.md` +
`induced_skills.json` + `skill_stats.json`（审计）。

- P0 复核（无 GPU）：真实规划器编译两条指令（active / cancelled 谓词）；
  真实 HTTP：下单后 `GET /orders` 200 且含订单号与「有效」，`/cancel/`
  后含「已取消」；v1/v2 头部含「我的订单」入口；门控注册前缺口 /
  注册后 covered；
- P1 沉淀（GPU）：新会话，编译技能真实下单 p3×2（0 LLM，cart→order
  active）；**同会话**（`reset=False`）`run_skill_hierarchy(fallback=True)`
  执行「查询我最近的订单状态」→ 真实 LLM 兜底成功；记录步数 /
  prompt tokens / 耗时；`TrajectoryRecorder` 留轨迹；
- P2 归纳：`induce_skill(task_q, records, catalog)` → 模板（无
  `{product}` 占位符）→ `register_induced_skill("order_query", ...)` →
  `save_induced_skills` → 门控 covered；
- P3 复用 3/3（技能路径，不加载模型）：
  - R1 同会话「查询我最近的订单状态」→ `orders_viewed` +
    `latest_order_active` ✓，0 LLM；
  - R2 真实 `env.cancel_order(order_id)` 后「查看我最近取消的订单状态」
    → `orders_viewed` + `latest_order_cancelled` ✓，0 LLM；
  - R3 新会话、v2 布局、`perturb_ids=True, perturb_prob=1.0`：编译技能
    真实下单 p4×1（0 LLM）后同指令技能路径 ✓，0 LLM；
- P4 效率对照表（P1 vs P3 各行）；
- P5 门禁：
  - `C:\Python311\python.exe -m pytest tests -q --tb=no --ignore=tests/test_locator.py --ignore=tests/test_progress_estimator.py --ignore=tests/test_smart_wait.py`
    （期望：179 基线 + 本 AR 新增，全过）；
  - `C:\Python311\python.exe scripts/ar011_eval.py`（30 场景，30/30、
    0 LLM，`success_rate==1.0` 与 `policy_steps==0`）。

决策：P1–P4 全成功 + 门禁全过 → `keep`；任一失败 → `rollback`
（负结果归档，不删产物）。

## 3. 关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| D1 | 状态谓词读服务端 `orders[-1].status`，不解析页面文本 | 与 AR001 验证红线一致：成功必须外部可执行确认；页面文案漂移不得影响判定 |
| D2 | 分支条件 `(查询\|查看) 且 订单`，含「取消」走 cancelled 谓词 | 确定性编译；「完成结算并提交订单」等结算指令不含查询/查看，不落入本分支（回归保护由单测固化） |
| D3 | 站点纯增量（新路由 + 头部链接），既有路由逐字段不变 | AR011 30 场景与全部既有测试的 DOM 语义不变；「我的订单」两布局同名，语义层可迁移（AR005 标准） |
| D4 | 模板无 `{product}` 占位符，复用 `_materialize` 空 targets 分支 | 技能库零改动；`induce_skill` 对无占位符轨迹天然成立（goto 保 URL、click 保名称） |
| D5 | skill_library / capability / runtime 零代码改动 | 证明「归纳注册表 + 统计 + 选择 + 显式缺口」机制的通用性：新操作类型不需要逐个打补丁 |
| D6 | LLM 兜底在同会话执行（`reset=False`） | `/api/reset` 会清空 `orders`，`run_task`/`run_hierarchy` 的 reset 语义会销毁前置真实订单；`run_skill_hierarchy(reset=False, fallback=True)` 是同一组合运行时的技能→兜底链，且保持会话连续（真实用户语义） |
| D7 | P3 三场景含一次真实 `/cancel/` 状态迁移 | 技能不依赖订单状态值：同一模板在 active/cancelled 两种真实服务端状态下分别通过对应谓词，证明技能与状态解耦 |

## 4. 测试设计（`tests/test_edge_order_query.py`）

纯逻辑（无浏览器）：

1. 规划器：「查询我最近的订单状态」→ `order_query`，谓词
   `["orders_viewed","latest_order_active"]`，targets 空，start_path `/`；
2. 规划器：「查看我最近取消的订单状态」→ 谓词含 `latest_order_cancelled`；
3. 规划器回归：「完成结算并提交订单」仍走 checkout 路径
   （`require_checkout=True`、operation 非 `order_query`）；
4. 验证器：真实 state 形状——空 orders 时两个状态谓词均 False；
   active 订单时 active True / cancelled False；`/cancel/` 后反转；
   `orders_viewed` 仅当 visited 含 `/orders`；
5. 能力门控：未注册 → `covered=False, no_skill_for_level_2`；注册两步入
   模板后 → `covered=True`（真实规划器 + 真实注册表）；
6. 物化：`order_query` 模板（无 `{product}`）经 `skill_for_subtask`
   物化后步骤名逐字不变（空 targets 分支）。

真实 HTTP（`LocalShopServer` + urllib，无浏览器）：

7. 站点：`/api/cart/set` 建车 → POST `/place-order` → `GET /orders` 200
   且含订单号与「有效」；`/cancel/{id}` 后 `GET /orders` 含「已取消」；
   v1 与 v2 头部均含「我的订单」入口；`/order/{id}` 旧页行为不变。

真实浏览器（`pytest.importorskip("playwright")`，模式同既有测试）：

8. 注册两步入技能 → `run_skill_hierarchy(fallback=False)` 真实执行：
   `compute_progress` 成功、`visited` 含 `/orders`、cart 不受影响、
   统计记 1/1（AR021 钩子自动覆盖）。

既有约束：AR019/AR020/AR021 全部测试不回退（179 基线全绿）。

## 5. 风险与对策

| 风险 | 对策 |
|------|------|
| 0.6B 兜底点不到新头部入口（P1 失败） | 诚实负结果：记录 rollback，不伪造归纳；PREDICATE_HINTS 中文提示 + 头部入口高显著性缓解 |
| 头部新链接挤占 24 元素预算 | 首页元素 ≤ 12，预算 24 不受影响；30 场景套件硬门禁兜底 |
| 站点改动破坏 AR011 30 场景 | 技能按名称匹配、新链接不与任何技能步骤同名；P5 门禁 30/30 + 0 LLM 校验 |
| `/api/reset` 销毁前置订单（D6 场景） | P1 用 `reset=False` 同会话链；评测脚本对会话顺序显式控制 |
| 规划器分支误吞结算指令 | 单测 3 固化回归；P5 全量 pytest 兜底 |

## 6. 回滚

- 代码：`git revert` 本 AR 提交（site/planner/verifier/policy 四处还原 +
  评测/测试移除）；
- 运行态：`clear_induced_skills()` + `clear_skill_stats()`；
- 已归档产物不动。

## 9.1 组合回退规则（沿用 AR001 design §9.1）

以 **A = 当前最优（AR021 状态：edge 179 passed；AR011 30/30、0 LLM；
AR021 复用 4/4、0 LLM）** 为初始最优。

1. B = A + 站点订单页/规划器/谓词（无技能路径）：B 的 30 场景与 edge
   套件必须 ≥ A（30/30、0 LLM、全过），否则回退 A；
2. C = B + 归纳闭环（P1 真实 LLM 兜底 + P2 归纳 + P3 技能复用 3/3、
   0 LLM）：C 在 B 基础上须真实达成「显式缺口 → LLM 沉淀 → 0-LLM 复用
   3/3（含 cancelled 状态迁移与 v2+churn 迁移）」，且 B 的全部门禁不回退，
   否则回退 B 并记录负结果；
3. 任何回退都写入 `ar022_report.md` 与 BACKLOG，不删除失败实验；
4. 全过 → 组合最优前移，README 版本递增。
