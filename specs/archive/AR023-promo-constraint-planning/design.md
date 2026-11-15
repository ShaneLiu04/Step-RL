# [AR023] 增量实现设计

## 1. 总体思路

「满减券」从**被静默丢弃的约束**（旧规划器照常编译、站点无券、服务端
无折扣、验证器读不到）升级为**与预算同级的一等约束**：

```
「购买…，结算时使用满400减50优惠」
  └─ plan_instruction(..., promos=fetch_promos(live))
       ├─ 基础编译（AR006 逻辑原样）→ spec(targets, require_checkout)
       └─ 促销后处理（对照真实 /api/promos + 实时目录价）：
            可行 → replace(spec, require_promo=True, promo=code)
            不可行（总额<门槛 / 券面不存在 / 无结算 / 无真实列表 / 泛称）
                 → None（显式拒绝，禁止静默降级）
  └─ decompose_task：checkout 子任务继承 require_promo/promo
  └─ skill_for_subtask：checkout_skill(promo) 在「提交订单」前
       插入 click button「领取{label}优惠」
  └─ 站点 place-order：实时价 total + state.promo 门槛判定
       → 订单 {total, paid, promo{code,discount,applied}}（服务端权威）
  └─ 验证器 order_promo_applied：只读 order.promo.applied ∧ code
```

核心不变式：

1. **成功判定只认服务端真实结算**（`order.promo.applied` / `paid`），
   页面文案与模型自述不参与；
2. **不可行即显式 `None`**（对照 AR006 预算超限语义）——券约束永不
   静默丢弃；
3. **站点/技能/谓词全部纯增量**：无促销码的 checkout 技能逐字段
   等价旧 4 步；既有路由行为逐字段不变；AR011 30 场景 DOM 语义不变；
4. **`/api/promos` 是唯一事实源**：页面按钮、规划器、技能步骤名
   全部从同一 `PROMOS` 常量派生，不存在三处各写一份的漂移。

## 2. 模块改动

### 2.1 `site.py`（纯增量）

- 新增 `Promo`（frozen dataclass：code/label/threshold/discount）与
  `PROMOS = {"man400jian50": 满400减50, "man2000jian150": 满2000减150}`；
- `SessionState`：尾部追加 `promo: Optional[Dict[str, object]] = None`；
  `reset()` 清零；`snapshot()` 增加 `"promo"`；
- `_Handler.do_GET` 新分支（置于页面路由前）：
  - `/api/promos` → `[{code,label,threshold,discount}, ...]`（200 JSON）；
  - `/promo/claim/{code}` → code ∈ PROMOS：`state.promo =
    {code, threshold, discount}`，200 `{"ok":true,"promo":...}`；
    否则 404「优惠码不存在」；
- `render_checkout` / `_render_v2_checkout`：表单卡片后新增
  「店铺优惠」卡片（每张券一个 form+button，`id='promo-claim-{code}'`，
  `aria-label='领取{label}优惠'`，`action='/promo/claim/{code}'`）；
- `do_POST /place-order`：先把实时价 `total` 计算上提（原预算检查复用
  同一 `total`，行为不变）；随后：
  ```python
  promo = dict(state.promo) if state.promo else None
  applied = bool(promo) and promo["code"] in PROMOS \
      and total >= int(promo["threshold"])
  discount = int(promo["discount"]) if applied else 0
  state.order = {"id":..., "items":..., "status":"active",
                 "total": total, "paid": total - discount,
                 "promo": {"code": promo["code"], "discount": discount,
                           "applied": applied} if promo else None}
  if applied:
      state.promo = None   # 券单张一次使用，消费掉
  ```
  既有 `id/items/status` 字段与错误分支（空车/缺姓名地址/库存/预算/
  称谓/路名/瞬时 500）逐字段不变；
- `render_order` / `_render_v2_order`：applied 时追加一行
  「优惠已抵扣 ¥{discount}，实付 ¥{paid}」；
- `LocalShopServer.__init__` 无新参数（促销是全局常量，非会话配置）。

### 2.2 `planner.py`

- `PromoInfo`（frozen dataclass）+ `fetch_promos(base_url)`（urllib，
  形状同 `fetch_catalog`）；
- `_PROMO_RE = re.compile(r"满\s*(\d+)\s*减\s*(\d+)")`；
- 现 `plan_instruction` 主体**原样**移入内部函数 `_compile_base`
  （含门控元组、预算/替代/移除/订单查询/mentions 全部分支）；
- 公开入口：
  ```python
  def plan_instruction(instruction, catalog, promos=None):
      spec = _compile_base(instruction, catalog)
      if not _coupon_mentioned(instruction):   # 满X减Y 或 优惠券/用券
          return spec                            # 既有路径零改动
      if spec is None or not spec.require_checkout or promos is None:
          return None
      match = _PROMO_RE.search(instruction)
      if match is None:
          return None                            # 仅泛称 → 拒绝
      threshold, discount = int(match.group(1)), int(match.group(2))
      promo = next((p for p in promos
                    if p.threshold == threshold and p.discount == discount),
                   None)
      if promo is None:
          return None
      total = sum(by_pid[pid].price * qty
                  for pid, qty in spec.targets.items() if pid in by_pid)
      if total < promo.threshold:
          return None
      return dataclasses.replace(spec, require_promo=True, promo=promo.code)
  ```
- `_coupon_mentioned`：`bool(_PROMO_RE.search(...)) or "优惠券" in s or "用券" in s`。

### 2.3 `tasks.py`

- `TaskSpec` 尾部追加（frozen dataclass，位置参数零破坏）：
  `require_promo: bool = False`、`promo: str = ""`；
- `predicate_names`：`require_checkout` 分支内，
  `order_placed` 之后 `if self.require_promo: names.append("order_promo_applied")`。

### 2.4 `hierarchical.py`

`decompose_task` 的 checkout 子任务 `TaskSpec(...)` 追加
`require_promo=task.require_promo, promo=task.promo`；add 子任务不变。

### 2.5 `skill_library.py`

- `from .site import PRODUCTS, PROMOS`；
- `checkout_skill(promo_code: str = "")`：
  ```python
  steps = [goto /checkout, type 收货人, type 地址]
  if promo_code and promo_code in PROMOS:
      steps.append(SkillStep("click", name=f"领取{PROMOS[promo_code].label}优惠",
                             role="button"))
  steps.append(SkillStep("click", name="提交订单", role="button"))
  ```
- `skill_for_subtask`：`if task.require_checkout: return
  checkout_skill(task.promo)`。
- 旧调用点（`ar014_checkpoint.py`、`test_edge_skill_library.py`、
  `test_edge_checkpoint.py` 的 `checkout_skill()`）零参调用 →
  输出与旧版逐字段一致（回归守卫由单测固化）。

### 2.6 `verifier.py` / `policy.py`

- `order_promo_applied(state, url)`：
  ```python
  order = state.get("order") or {}
  promo = order.get("promo") or {}
  return bool(promo.get("applied")) and promo.get("code") == task.promo
  ```
  注册进 `_predicates` 返回表；
- `PREDICATE_HINTS["order_promo_applied"] = "领取满减优惠并提交订单"`
  （LLM 提示词路径用，判定仍只认服务端）。

### 2.7 `runtime.py` / `capability.py`

- `run_task`：`promos = fetch_promos(env.server.base_url)`，
  两处 `plan_instruction(instruction, catalog, promos)`；
- `check_capability(instruction, catalog, promos=None)`：透传；
  既有两参调用（AR011 评测等）行为不变。

### 2.8 `scripts/ar023_baseline_probe.py`（改动前执行，旧代码留证）

全部真实执行（旧代码）：

- A 规划器：8 条指令 → 旧 `plan_instruction` 真实编译结果
  （记录 targets/require_checkout/level；4 条不可行指令被照常编译
  = 「静默丢约束、保留成功」实锤）；
- B 站点：真实 `GET /api/promos` → 404；真实 `GET /checkout`（v1 与
  v2）HTML 中无「领取…优惠」元素；
- C 执行：真实会话（urllib + cookie）建车 p3+p4 → 真实
  `POST /place-order` → 订单 JSON 无 `total/paid/promo` 字段；
  旧 `checkout_skill().steps` 无领取步；旧验证器谓词表无
  `order_promo_applied`；
- 输出 `outputs/ar023/baseline_probe.{json,md}`。

### 2.9 `scripts/ar023_eval.py`（改动后主评测）

结构对齐 AR020/AR022：`set_seed(42)`；P0–P5；每阶段落盘
`outputs/ar023/eval/ar023_results.json` + `ar023_report.md`。

- P0 复核（无 GPU，真实 HTTP + 真实规划器 + 真实门控）：
  8 条指令编译 vs 期望表（4 spec / 4 None，字段级比对）；
  `/api/promos` 200 两券；v1/v2 结算页含两个 `aria-label`；
  真实全流程 A（p3+p4 领取后下单：total=598 / paid=548 / applied=True，
  券消耗后 state.promo=None）；真实全流程 B（仅 p3 领取后下单：
  applied=False / paid=199 / 券不消耗）；
  `check_capability(C1, catalog, promos)` covered 且技能含领取步；
- P1/P2/P3 真实 Edge 执行（`run_skill_hierarchy(fallback=False)`，
  0 LLM，`BrowserEnv(server, channel="msedge", headless=True,
  semantic=True)`）：
  - T1 v1：C1 全链路（2 个 add 子任务 + promo checkout 子任务），
    断言 success、`order.total=598`、`paid=548`、`promo.code`、
    `applied=True`、步骤全部 `source=="skill"`、秒级计时；
  - T2 v1：C3（p3×3，597→547）；
  - T3 v2 + `perturb_ids=True, perturb_prob=1.0` 新会话：C2（p1×1，
    6999→6849，man2000jian150）；
- P4 效率/收益对照：读 `baseline_probe.json` 的旧订单（paid=total、
  无 promo）vs P1–P3 实付（立减 50/150）；LLM 调用两侧 0；
  步数：旧 4 步 vs 新 5 步（+1 领取步）；
- P5 门禁：
  - `C:\Python311\python.exe -m pytest tests -q --tb=no --ignore=tests/
    test_locator.py --ignore=tests/test_progress_estimator.py
    --ignore=tests/test_smart_wait.py`（期望 189 基线 + 新增全过）；
  - `C:\Python311\python.exe scripts/ar011_eval.py`（30/30、0 LLM、
    `policy_steps==0`）。

决策：P0 全过 + P1–P3 3/3（服务端 applied=True）+ 门禁全过 →
`keep`；任一失败 → `rollback`（负结果归档，不删产物）。

## 3. 关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| D1 | 不可行（总额<门槛/券面不存在/无结算/无真实列表/泛称）一律 `None` | AGENTS.md §1：不允许静默降级为成功；对照 AR006 预算超限显式失败语义；C4–C7 四组指令是回归守卫 |
| D2 | 可行性用**实时目录价**计算 | 规划器既有原则（读 live catalog 而非静态价）；churn/价格漂移场景下计划仍然可信 |
| D3 | `/api/promos` 为唯一事实源，页面/规划器/技能名同源派生 | 消除「页面展示的券」与「计划里用的券」漂移；站点纯常量（可审计） |
| D4 | 折扣结算只在 `place-order` 服务端发生，验证器只读订单字段 | 成功外部可执行确认（AR001 验证红线）；客户端/页面文案不参与判定 |
| D5 | 券消费语义：applied → 消耗；applied=False → 不消耗 | 真实商城单券一次使用；贴线失败（398）后券可再用于下一单，诚实留痕 |
| D6 | `checkout_skill` 增量步而非新操作/新技能 | 领取是 checkout 流程内一步，不是独立操作；无促销码时逐字段等价旧技能 → AR011 30 场景/AR014 检查点/AR015 等全链零风险 |
| D7 | 本 AR 无 LLM 落点（0 LLM 全程） | 能力链（add 子任务 + promo checkout 子任务）全部编译技能可覆盖；AR019 归纳链无需介入——「技能全覆盖」本身是能力门控的目标态 |
| D8 | 规划器促销后处理置于基础编译之后（不改 `_compile_base` 内部分支） | AR006 全部既有分支逐字段不变，回归面最小；预算/替代/移除/查询与券的交叉场景天然被后处理覆盖 |

## 4. 测试设计（`tests/test_edge_promo_planning.py`，22 项）

纯逻辑（无浏览器）：

1. C1 可行多商品 → `require_promo=True`、`promo="man400jian50"`、
   targets/require_checkout 正确、`predicate_names` 链尾含
   `order_promo_applied`；
2. C2 大额券 → `man2000jian150`；
3. C3 数量场景（p3×3=597≥400）→ 可行；
4. C4（199<400）→ `None`；
5. C5（398<400 贴线）→ `None`；
6. C6（满999减99 虚构券面）→ `None`；
7. C7（无结算动作）→ `None`；
8. 泛称「使用优惠券结算」无满X减Y → `None`；
9. `promos=None` 时 C1 → `None`（无真实列表即拒绝）；
10. 回归：无券字「购买无线充电器和蓝牙耳机并结算」→ 既有 spec 且
    `require_promo=False, promo=""`；
11. 回归：AR022 订单查询指令规划结果不变；
12. 验证器：真实 state 形状——applied+code 匹配 True；code 不匹配
    False；无 promo False；
13. `predicate_names`：纯 checkout 任务逐字段不变（回归守卫）；
14. `decompose_task`：checkout 子任务继承 `require_promo/promo`；
15. `checkout_skill("man400jian50")`：领取步名
    「领取满400减50优惠」在「提交订单」前；`checkout_skill()`
    与旧 4 步逐字段一致（回归守卫）；

真实 HTTP（`LocalShopServer` + urllib，无浏览器）：

16. 全流程：`/api/promos` 200 两券 → 建车 p3+p4 → 结算页（v1 与 v2）
    均含两个领取按钮 → claim man400jian50 → 下单 →
    total=598 / paid=548 / applied=True / 券消耗（state.promo None）；
17. 贴线：仅 p3（199）claim 后下单 → applied=False / paid=199 /
    券不消耗（state.promo 保留）；再次凑够 400 下单 → applied=True
    （同一张券真实复用）；

真实浏览器（`pytest.importorskip("playwright")`）：

18. C1 真实 Edge 全链路 `run_skill_hierarchy(fallback=False)`：success、
    步骤全 `source=="skill"`（0 LLM）、`order.promo.applied=True`、
    paid=548、`state.promo=None`。

既有约束：AR001–AR022 全部测试不回退（189 基线全绿）。

## 5. 风险与对策

| 风险 | 对策 |
|------|------|
| 结算页新增卡片挤占 24 元素预算 | 结算页元素 ≤ 8（含新卡片）；AR013 注入场景亦有余量；AR011 30 场景 + 全套件硬门禁兜底 |
| `place-order` 重构（total 上提）引入行为漂移 | 错误分支与既有订单字段逐字段保留；189 基线测试 + AR011 30 场景双门禁 |
| 规划器签名变更遗漏调用点 | 新参数可选（默认 None）；`grep plan_instruction` 全调用点清点（scripts/tests/step_rl）；既有测试两参调用全绿 |
| 券消费语义导致评测会话状态串扰 | 每个执行场景新会话（新 server）；P0 全流程 B 验证「不消耗」分支 |
| `dataclasses.replace` 破坏 frozen 语义 | replace 生成新实例，原 spec 不可变语义不变（单测 10/13 固化） |
| v2 布局领取按钮 DOM 差异 | 按钮仅靠 `aria-label`（accessible name）定位，与 v1 同名；P3 真实 v2+churn 执行覆盖 |

## 6. 回滚

- 代码：`git revert` 本 AR 提交（site/planner/tasks/hierarchical/
  skill_library/verifier/policy/runtime 八处还原 + 评测/测试移除）；
- 运行态：无需（技能为编译式，注册表无本 AR 条目）；
- 已归档产物不动。

## 9.1 组合回退规则（沿用 AR001 design §9.1）

以 **A = 当前最优（AR022 状态：edge 189 passed；AR011 30/30、0 LLM；
AR022 复用 3/3、0 LLM）** 为初始最优。

1. B = A + 站点促销/规划器/谓词/技能扩展（无真实执行）：B 的 edge 套件
   与 AR011 30 场景必须 ≥ A（189 全过、30/30、0 LLM），否则回退 A；
2. C = B + 真实执行证据（P0 规划 8/8 含 4 组诚实 None、P1–P3 三场景
   3/3 服务端 applied=True 且 paid 正确）：C 在 B 基础上须真实达成
   「规划准确率 100%（对照旧代码真实基线 0/8）+ 0 LLM + 权威折扣
   结算」，且 B 的全部门禁不回退，否则回退 B 并记录负结果；
3. 任何回退都写入 `ar023_report.md` 与 BACKLOG，不删除失败实验；
4. 全过 → 组合最优前移，README 版本递增（v4.12）。
