# [AR022] 任务清单

| # | 任务 | 状态 |
|---|------|------|
| T1 | spec 三件套 + BACKLOG 认领 B04 | passing（commit 8116e79） |
| T2 | 改动前基线探针（旧代码真实执行：规划器 None + /orders 404 + 无技能落点） | passing（探针 outputs/ar022/baseline_probe.json：plan 双指令 None、门控 planner_unsupported、GET /orders 404、induced_operations 无 order_query、/order 页无状态文案） |
| T3 | 实现 `site.py`（/orders 路由 + render_orders + v1/v2 头部「我的订单」） | passing（commit 08b8cfd） |
| T4 | 实现 `planner.py`（门控关键词 + order_query 分支） | passing（commit 08b8cfd） |
| T5 | 实现 `verifier.py`（orders_viewed / latest_order_active / latest_order_cancelled）+ `policy.py`（PREDICATE_HINTS） | passing（commit 08b8cfd） |
| T6 | 单测 `tests/test_edge_order_query.py`（10 项：4 规划器 + 2 验证器 + 2 门控/物化 + 1 真实 HTTP + 1 真实浏览器） | passing（10/10；全套件 189 passed, 3 skipped, 73.41s） |
| T7 | 主评测 `scripts/ar022_eval.py` P0–P5（真实 Edge / GPU / 服务端状态） | passing（decision=keep；P1 兜底 1 步 186/19 tokens 3.13s；P2 1 步模板；P3 复用 3/3 0.30–0.31s 0 LLM（含 v2+churn）；P5 门禁全过） |
| T8 | 组合门禁（edge pytest + AR011 30 场景） | passing（189 passed = 179 基线 + 10 新增，零回退；AR011 30/30、policy_steps=0、prompt_tokens=0） |
| T9 | README 5.22（插 EX001 前，EX001 顺延 5.23）+ 5.1/5.6/演进/版本/快速开始/目录树/徽章 + REPRODUCTION + BACKLOG B04 毕业 + cover 重生成 | passing |
| T10 | spec 归档（git mv specs/archive/）+ 自查记录 | passing |
| T11 | gitee 双历史增量同步，收尾校验 diff 为空 | passing（7 组增量提交 8200d5b→f39e5d6，每组 <50KB，push 后 `git diff -w --stat gitee/main main` 为空） |

## 执行记录

- **T2 基线探针（旧代码，AR021 状态）**：A 规划器缺口——`查询我最近的订单状态`
  与 `查看我最近取消的订单状态` 均 plan_instruction=None，check_capability →
  `planner_unsupported`；B 站点缺口——真实 `GET /orders` → HTTP 404
  「页面不存在」（同会话真实下单成功：status=active），单订单成功页不含
  「有效/已取消」文案；C 注册表缺口——induced_operations=[]，无
  order_query 落点。
- **T7 评测真实数字**（`outputs/ar022/eval/ar022_results.json`）：
  P0 规划双指令 order_query（active/cancelled 谓词）、/orders 真实 200 渲染
  订单号+「有效」、真实 /cancel 后「已取消」、v1/v2 头部入口、门控
  no_skill_for_level_2 → covered；P1 编译技能真实下单 p3×2（10 步 1.87s
  0 LLM，订单 414abfa63c active，cart 清空），同会话 LLM 兜底（GPU，
  AR004 适配器）**1 步**（thought「打开购物车」→ click e3「我的订单」，
  φ 0→1），186 prompt / 19 response tokens，3.13s，visited 含 /orders；
  P2 归纳 1 步模板 `click link 我的订单`（induced_order_query），门控
  covered；P3 R1 active 0.30s / R2 真实 /cancel 后 cancelled 谓词 0.30s /
  R3 v2+churn 新订单 55b645cab0（p4）0.31s，均 0 LLM，统计 attempts=3
  successes=3 rate=1.0 未淘汰；P5 pytest 189 passed 3 skipped（73.61s），
  AR011 rc=0：30 任务 success_rate=1.0 policy_steps=0 skill_steps=276
  prompt_tokens=0（81.66s）。
- **T11 gitee 同步**：按 AGENTS.md §6 执行（worktree 增量、~50KB/提交、
  结束 `git diff -w --stat gitee/main main` 为空）。

## devflow-review 独立自查（findings + verdict）

对 spec / 代码 / 评测产物按独立评审标准复查：

1. **[info] 归纳模板无占位符（1 步 click）**：LLM 兜底从下单成功页一步
   点击头部「我的订单」（该入口在每页头部恒可见）；归纳器保持轨迹原样
   （不自行裁剪）。若轨迹更长（如先 goto /），模板会含 goto 步——1 步
   是真实环境的真实结果，186 tokens 是本次环境的真实沉淀成本。
2. **[info] `/api/reset` 会销毁 orders（设计 D6 的已知限制）**：
   `run_task`/`run_hierarchy` 的 reset 语义不适合「先下单后查询」场景；
   P1 用 `run_skill_hierarchy(reset=False, fallback=True)` 同会话执行
   （组合运行时的技能→兜底链，会话连续，贴近真实用户）。不影响既有
   30 场景（其任务链内无跨 reset 的订单状态依赖）。
3. **[info] 谓词口径 = `orders[-1].status`（服务端时序最新单）**：
   「最近订单」以服务端 orders 数组为准；/cancel 只改 status 不移动
   订单，故「active → cancelled」状态迁移被真实观测（P3 R2）。
4. **[verified] 回归保护**：结算指令「完成结算并提交订单」不落入
   order_query 分支（test_planner_checkout_not_misrouted 固化）；
   既有 179 测试 + AR019/020/021 全部不回退（门禁 189 passed 全绿）。
5. **[verified] 技能库零改动（D5）**：order_query 走既有 `_INDUCED`
   通用路径——未注册显式缺口 `no_skill_for_level_2`，注册后
   `_materialize` 空 targets 分支；AR021 统计钩子自动覆盖（P3 审计
   attempts=3/successes=3/rate=1.0 留痕）。
6. **[verified] 指标来源**：README 5.22 全部数字来自
   `outputs/ar022/**` 真实执行日志（P1 186 tokens/3.13s；P3 0.30–0.31s；
   门禁 189 passed + AR011 30/30 policy_steps=0），无 mock / 硬编码。

**verdict：PASS（keep）**——无阻断性 finding；B（站点/规划/谓词层，30
场景 + 套件不回退）与 C（真实 LLM 沉淀 → 归纳 → 0-LLM 复用 3/3，含取消态
迁移与 v2+churn 迁移）均按 design §9.1 达成，组合最优前移至 AR022。
