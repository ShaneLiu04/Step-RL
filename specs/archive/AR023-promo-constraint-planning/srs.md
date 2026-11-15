# [AR023] 优惠券/促销约束规划（promo constraint planning）需求设计说明书

## 1. 背景与目标

AR006 让自然语言约束（预算/最便宜/最贵/缺货替代）被**确定性编译**为
TaskSpec，但约束集合里没有「促销」这一类：真实高频指令
「购买无线充电器和蓝牙耳机，结算时使用满400减50优惠」在改动前代码上被
**静默降级**——改动前基线探针（`scripts/ar023_baseline_probe.py`，旧代码真实
执行，`outputs/ar023/baseline_probe.json`）暴露三层缺口：

1. **规划器静默丢约束**：`plan_instruction` 对 8 条优惠券指令全部编译出
   「无促销约束」的 spec（TaskSpec 无 require_promo 字段）；对不可行指令
   （总额 199 < 400、总额 398 贴线低于 400、虚构券 满999减99、无结算动作）
   也照常编译出看似成功的 spec——**约束被丢弃，成功被保留**，正是 AGENTS.md
   §1 禁止的「静默降级为成功」；
2. **站点无促销支撑**：真实 `GET /api/promos` → 404「页面不存在」；结算页
   （v1/v2）无任何领取优惠元素；真实下单产出的订单 JSON 无
   `total/paid/promo` 字段，服务端无法权威确认「优惠是否真的生效」；
3. **验证器无促销谓词**：谓词表没有 `order_promo_applied`，即使订单带上了
   优惠，成功判定也读不到——用户期望「用上了券」无法被外部验证。

目标（BACKLOG B05）：满减券成为与预算同级的**一等约束**——规划器对照
**真实促销列表**（`/api/promos`）与**实时目录价**做确定性可行性判定
（可行 → `require_promo` + 真实促销码；不可行 → 显式 `None` 拒绝，不猜测
不降级）；站点在结算页提供真实领取交互，服务端在下单时权威结算折扣
（`total/paid/promo.applied`）；验证器以服务端 `order.promo.applied` 判定；
编译结算技能按促销码插入「领取…」步，0-LLM 执行。验收：8 条真实指令
**规划准确率 100%**（对照 naive 基线 0/8）+ 3 个真实执行场景 3/3、
0 LLM、服务端确认 applied=True 与实付金额。

## 2. 范围

- `step_rl/edge/site.py`：`Promo`/`PROMOS` 常量（满400减50、满2000减150）、
  `GET /api/promos`、`GET /promo/claim/{code}`、v1/v2 结算页真实领取按钮、
  `place-order` 服务端折扣结算（`total/paid/promo`，用券消耗语义）、
  订单成功页实付渲染（**纯增量**：既有路由行为逐字段不变）；
- `step_rl/edge/planner.py`：`fetch_promos`、`_PROMO_RE`、
  `plan_instruction(instruction, catalog, promos=None)` 促销后处理
  （既有编译逻辑原样保留为内部函数）；
- `step_rl/edge/tasks.py`：`TaskSpec` 尾部追加 `require_promo: bool = False`、
  `promo: str = ""`（位置参数零破坏）；`predicate_names` 在 checkout 链尾
  追加 `order_promo_applied`；
- `step_rl/edge/hierarchical.py`：`decompose_task` 的 checkout 子任务继承
  `require_promo/promo`；
- `step_rl/edge/skill_library.py`：`checkout_skill(promo_code="")` 按促销码
  插入「领取{label}优惠」步（无促销码时逐字段等价旧 4 步）；
  `skill_for_subtask` 传 `task.promo`；
- `step_rl/edge/verifier.py`：`order_promo_applied`（读服务端 `order.promo`）；
- `step_rl/edge/policy.py`：`PREDICATE_HINTS` 加 `order_promo_applied`；
- `step_rl/edge/runtime.py` / `capability.py`：`plan_instruction` 调用点
  传入 `fetch_promos` 结果（`check_capability` 增可选 `promos` 参数）；
- 评测 `scripts/ar023_eval.py`（真实 Edge / 服务端状态，0 LLM）与改动前
  基线探针 `scripts/ar023_baseline_probe.py`；
- 单测 `tests/test_edge_promo_planning.py`；
- 不在范围：v3 布局（B06）、并发隔离（B07）、观测缓存（B08）、B03 剩余
  的长度平局裁决、多券组合/券的过期与适用范围细化、LLM 兜底路径
  （本 AR 的能力链全程技能可覆盖，无 LLM 落点）；不训练新模型；
  不修改 AR001–AR022 已归档内容。

## 3. 功能需求

### FR1 站点促销支撑（`site.py`，纯增量）

- `PROMOS`：`man400jian50`（满400减50）、`man2000jian150`（满2000减150）
  （服务端常量，代码与页面共用同一来源，保证「页面展示的券」与
  「规划器/技能看到的券」一致）；
- `GET /api/promos`：真实促销列表 JSON（code/label/threshold/discount）；
- `GET /promo/claim/{code}`：code 在 `PROMOS` 中 → 会话级
  `state.promo = {code, threshold, discount}`（可被下次下单消耗）；
  未知 code → 404「优惠码不存在」；
- v1/v2 结算页新增「店铺优惠」卡片：每张券一个真实按钮
  `aria-label='领取满400减50优惠'` / `'领取满2000减150优惠'`
  （两布局 accessible name 相同——语义层跨布局迁移前提，AR005 标准）；
- `POST /place-order`：以**实时价**计算 `total`；`state.promo` 已领取且
  `total ≥ threshold` → `promo = {code, discount, applied: true}`、
  `paid = total − discount`，并**消耗**该券（`state.promo = None`，
  单张券一次使用）；已领取但 `total < threshold` → `applied: false`、
  `paid = total`、券**不消耗**（诚实留痕：尝试过但未生效）；未领取 →
  `promo: null`；订单新增 `total/paid/promo` 字段，既有
  `id/items/status` 逐字段不变；
- `SessionState.promo` 新字段（`reset()` 清零；`/api/state` 快照含
  `promo` 与订单新字段）；订单成功页（v1/v2）在 applied 时渲染
  「优惠已抵扣 ¥X，实付 ¥Y」；
- 既有路由（`/`、`/search`、`/product/`、`/add/`、`/update/`、`/remove/`、
  `/cart`、`/checkout`、`/orders`、`/order/{id}`、`/cancel/`、`/api/*`
  既有字段）行为逐字段不变。

### FR2 规划器促销约束（`planner.py`）

- `fetch_promos(base_url)`：读真实 `/api/promos` → `PromoInfo` 列表；
- 门控：指令含「满X减Y」（`_PROMO_RE`）或「优惠券/用券」字样即进入
  促销后处理；
- 后处理规则（确定性，无猜测）：
  1. 基础 spec 不可编译（`None`）→ 保持 `None`；
  2. 基础 spec `require_checkout == False`（券无法在无订单时生效）→
     `None`（显式拒绝）；
  3. 调用方未传真实促销列表（`promos=None`）→ `None`（不依赖静态
     假设的券面）；
  4. 指令只有泛称「优惠券」而无「满X减Y」→ `None`（无法唯一确定券面）；
  5. 「满X减Y」与真实促销列表 (threshold, discount) 不匹配 → `None`
     （不存在的券不猜）；
  6. 按**实时目录价**计算 spec 目标总额 < threshold → `None`
     （不可行不降级——对照 AR006 预算超限的显式失败语义）；
  7. 全部通过 → `dataclasses.replace(spec, require_promo=True,
     promo=code)`。
- 回归保护：不含券字的指令走原逻辑，编译结果逐字段不变（既有
  planner/runtime/order_query/batch_remove 全部单测为硬约束）。

### FR3 任务/分解/技能（`tasks.py` / `hierarchical.py` / `skill_library.py`）

- `TaskSpec.require_promo/promo`：frozen dataclass 尾部追加，
  位置参数兼容；
- `predicate_names`：`require_checkout and require_promo` →
  链尾追加 `order_promo_applied`（其余任务形态逐字段不变）；
- `decompose_task`：checkout 子任务继承 `require_promo/promo`
  （子任务级成功判定因此包含促销谓词——领取必须发生在提交订单前）；
- `checkout_skill(promo_code="")`：促销码有效时，在「提交订单」前插入
  `click button「领取{label}优惠」`；`promo_code=""` 时输出与旧 4 步
  **逐字段一致**（回归守卫）；
- `skill_for_subtask`：`task.require_checkout` →
  `checkout_skill(task.promo)`（非 checkout 子任务不受影响）。

### FR4 验证器真实促销谓词（`verifier.py`）

- `order_promo_applied`：服务端 `state.order.promo` 非空、
  `applied == True` 且 `code == task.promo`（只认服务端权威结算结果，
  不信任页面文案与模型自述）；
- 注册进谓词表；`policy.PREDICATE_HINTS` 增加对应中文提示
  （LLM 提示用，非判定路径）。

### FR5 组合运行时/能力门控（`runtime.py` / `capability.py`）

- `run_task`：`promos = fetch_promos(...)` 后 `plan_instruction(instruction,
  catalog, promos)`（重规划同样传入）；
- `check_capability(instruction, catalog, promos=None)`：透传给规划器；
  无 `promos` 时优惠券指令显式 `planner_unsupported`（与规划器
  「无真实列表即拒绝」语义一致）。

### FR6 评测（`scripts/ar023_eval.py`）与基线探针（`scripts/ar023_baseline_probe.py`）

基线探针（改动前、旧代码、真实执行）：

- A 规划器静默丢约束：8 条指令在旧 `plan_instruction` 上的真实编译结果
  （含 4 条不可行指令被照常编译成「成功 spec」的实锤）；
- B 站点缺口：真实 `GET /api/promos` → 404；v1/v2 结算页 HTML 无
  「领取…优惠」元素；
- C 执行缺口：旧代码真实会话建车（p3+p4）→ 无领取路径 → 真实下单 →
  订单 JSON 无 `total/paid/promo`；旧编译结算技能步骤无领取步；
  旧验证器谓词表无 `order_promo_applied`。

主评测（改动后，真实 Edge `channel=msedge` + 真实服务端状态，0 LLM）：

| 阶段 | 内容 |
|------|------|
| P0 | 改动后复核（无 GPU）：8 条指令规划器真实编译（4 spec + 4 None）vs 用户期望；`/api/promos` 真实 200 两张券；v1/v2 结算页真实渲染领取按钮；真实 HTTP 全流程（建车 p3+p4 → 领取 → 下单 → 服务端 applied=True、paid=total−50；贴线 398 场景 applied=False 且券不消耗）；门控 covered |
| P1 | 真实执行 T1（v1）：C1「购买无线充电器和蓝牙耳机，结算时使用满400减50优惠」全链路技能路径，0 LLM，服务端确认 total=598 / paid=548 / applied=True |
| P2 | 真实执行 T2（v1）：C3「购买3件无线充电器…满400减50」（398 贴线反例之外的可行数量场景，total=597 → paid=547） |
| P3 | 真实执行 T3（v2 布局 + 全量 ID churn、新会话）：C2「购买 iPhone 15…满2000减150」（total=6999 → paid=6849） |
| P4 | 效率/收益对照：naive（旧代码真实订单：无折扣，paid=total）vs 新（实付立减 50/150）；步数差 +1；LLM 调用两侧均为 0 |
| P5 | 组合门禁：edge 全套件 pytest（189 基线 + 新增，全过）+ AR011 30 场景（30/30、0 LLM）+ 本 AR 三场景 3/3 |

8 条评测指令与用户期望（真实目录价 p1=6999 / p2=59 / p3=199 / p4=399）：

| # | 指令 | 期望 |
|---|------|------|
| C1 | 购买无线充电器和蓝牙耳机，结算时使用满400减50优惠 | `{p3:1,p4:1}` 结算 + man400jian50 |
| C2 | 购买iPhone 15，结算时使用满2000减150优惠 | `{p1:1}` 结算 + man2000jian150 |
| C3 | 购买3件无线充电器并结算，使用满400减50优惠 | `{p3:3}` 结算 + man400jian50 |
| C4 | 购买无线充电器，结算时使用满400减50优惠 | `None`（199 < 400 不可行） |
| C5 | 购买2件无线充电器，结算时使用满400减50优惠 | `None`（398 < 400 贴线不可行） |
| C6 | 购买无线充电器和蓝牙耳机，结算时使用满999减99优惠 | `None`（券面不存在） |
| C7 | 搜索无线充电器，使用满400减50优惠 | `None`（无结算动作，券无处生效） |
| C8 | 买最贵的商品结算，并用满2000减150优惠 | `{p1:1}` 结算 + man2000jian150 |

### FR7 文档

README 5.x 新章节（插入 EX001 之前，EX001 顺延编号）、5.1 结果表、
5.6 回退记录、AR 演进表、版本表（v4.12）、快速开始、目录树、测试徽章、
头部摘要；`docs/REPRODUCTION.md` 复现命令与结果表；BACKLOG B05 毕业
记录；`docs/images/cover.jpg` 重生成。

## 4. 非功能

- 既有 189 项 edge 测试不得回退（AR001–AR022 全绿为硬约束）；
- 站点改动纯增量：AR011 30 场景套件、AR013 对抗注入、AR014 检查点
  等既有行为的 DOM 语义不变（结算页新增一张卡片，元素按名称匹配，
  不与既有技能步骤同名冲突）；
- 不新增依赖、不训练新模型、不引入 LLM 调用；所有指标来自真实执行日志
  （`outputs/ar023/**`），禁止 mock / 硬编码 / 随机数。

## 5. 假设

- 规划器对券面的解析（满X减Y）覆盖真实用户指令形态；更复杂表述
  （「第二件半价」等）不在本期范围，按 FR2 规则 4 显式拒绝；
- 促销为服务端常量（两档），与预算约束一样属于「站点可见、代码可审计」
  的确定性输入；真实商城的券动态下发不改变本 AR 的判定口径
  （`/api/promos` 是唯一事实源）；
- 单张券会话内一次使用（消费语义）；跨会话券账户不在本期范围。

## 6. 术语

- 满减券（promo）：服务端常量定义的门槛-折扣对，`/api/promos` 为
  唯一事实源；
- 促销后处理：规划器在基础编译完成后对照真实促销列表做的确定性
  可行/不可行判定（可行 → `require_promo`；不可行 → `None`）；
- 权威折扣结算：`place-order` 以实时价 + 已领取券面计算
  `total/paid/promo.applied` 并写入订单 JSON，验证器只读该字段；
- 静默降级：约束被丢弃但任务仍「成功」的反模式（AGENTS.md §1 红线，
  本 AR 以 C4–C7 四组不可行指令为回归守卫）。
