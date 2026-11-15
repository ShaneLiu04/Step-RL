# [AR023] 任务清单

| # | 任务 | 状态 |
|---|------|------|
| T1 | spec 三件套 + BACKLOG 认领 B05 | passing |
| T2 | 改动前基线探针（旧代码真实执行：8 指令静默丢约束 + /api/promos 404 + 订单无折扣字段） | passing |
| T3 | 实现 `site.py`（PROMOS / /api/promos / /promo/claim / 结算页领取按钮 / place-order 权威折扣 / 订单新字段 / 成功页实付） | passing |
| T4 | 实现 `planner.py`（PromoInfo / fetch_promos / 促销后处理）+ `tasks.py`（require_promo/promo + predicate_names）+ `hierarchical.py`（分解继承） | passing |
| T5 | 实现 `skill_library.py`（checkout_skill(promo)）+ `verifier.py`（order_promo_applied）+ `policy.py`（hint）+ `runtime.py`/`capability.py`（透传 promos） | passing |
| T6 | 单测 `tests/test_edge_promo_planning.py`（22 项） | passing |
| T7 | 主评测 `scripts/ar023_eval.py` P0–P5（真实 Edge / 服务端状态，0 LLM） | passing |
| T8 | 组合门禁（edge pytest + AR011 30 场景） | passing |
| T9 | README 5.23（插 EX001 前，EX001 顺延 5.24）+ 5.1/5.6/演进（含 AR022 补行）/版本 v4.12/快速开始/目录树/徽章/头部 + REPRODUCTION + BACKLOG B05 毕业 + cover 重生成 | passing |
| T10 | spec 归档（git mv specs/archive/）+ devflow-review 自查记录 | passing |
| T11 | gitee 双历史增量同步，收尾校验 diff 为空 | passing |

## 执行记录

- **T1**：提交 `7b9e601`。B05 在候选队列标记 `claimed by AR023`。
- **T2**：提交 `070e0a6`。旧代码真实执行（`outputs/ar023/baseline_probe.{json,md}`）：
  A 层——8 条优惠券指令在旧 `plan_instruction` 上全部编译出无促销约束的
  spec，其中 C4（199<400）、C5（398<400 贴线）、C6（满999减99 虚构券面）、
  C7（无结算动作）四条不可行指令被照常编译成「成功计划」（静默丢约束、
  保留成功实锤）；旧 TaskSpec 无 require_promo/promo 字段（约束不可表示）。
  B 层——真实 `GET /api/promos` → HTTP 404「页面不存在」；v1/v2 结算页
  HTML 均无「领取…优惠」元素。C 层——旧代码真实会话建车 p3+p4 下单：
  订单 JSON 仅 `{id, items, status}`，无 total/paid/promo；旧
  `checkout_skill()` 4 步无领取步；旧验证器谓词表无 `order_promo_applied`。
- **T3–T5**：提交 `fca71ad`。实现中实测修正两处真实问题：
  1. `/promo/claim/{code}` 若 303 重定向回 `/checkout`，会重新渲染结算页、
     重置已填的收货人/地址 DOM 值 → 提交订单 POST 空值被服务端拒单
     （实测进度 5/9，缺 name_filled/address_filled/order_placed/
     order_promo_applied）；改为**无导航 AJAX 领取**（真实商店的优惠券
     领取模式，页面 DOM 与表单值保留）；
  2. `fetch` fire-and-forget 存在「提交订单抢跑领取请求」的竞态 →
     领取改为点击处理器内**同步 XHR**，服务端确认先于浏览器/代理继续，
     竞态消除（单测 + 3 场景真实执行验证）。
- **T6**：22 项单测（9.12s）：规划可行 4（C1/C2/C3/C8 含券码断言）+
  不可行 6（C4/C5/C6/C7/泛称/无真实列表）+ 回归 2（无券 checkout、
  订单查询）+ 谓词表回归 1 + 验证器真实 state 形状 1 + 分解继承 1 +
  技能步序/字段级回归 2 + 门控 1 + 真实 HTTP 全流程（v1+v2）1 +
  贴线不消耗/同券复用 1 + 真实 Edge 全链路 0 LLM 1。
  全套件 **211 passed, 3 skipped**（189 基线零回退 + 22 新增）。
- **T7**（`outputs/ar023/eval/ar023_results.json` + `ar023_report.md`）：
  P0——8 指令真实编译 8/8（4 spec 券码全对 + 4 组诚实 None：199<400、
  398 贴线差 1 元、虚构券面、无结算）；`/api/promos` 200 两券；v1/v2
  结算页真实渲染两个领取按钮；真实全流程 A（p3+p4 领取→下单：
  total=598/paid=548/applied=True/券消耗，v1 与 v2 各一单）；贴线路径 B
  （199→applied=False、paid=199、券不消耗；同券再凑满 598→548 真实复用）；
  门控 covered（add_item×2 + checkout）。P1 T1（v1）17 步 0 LLM 3.17s
  598→548；P2 T2（v1，p3×3）11 步 0 LLM 2.08s 597→547；P3 T3
  （v2+全量 ID churn、新会话）11 步 0 LLM 2.14s 6999→6849。
  三场景订单均由服务端 `order.promo` 字段权威确认。
- **T8**：edge 套件 pytest **211 passed, 3 skipped**（83.7s，rc=0）；
  AR011 30 场景 **rc=0、success_rate=1.0、policy_steps=0、prompt_tokens=0**
  （109.8s）。legacy 三文件 17 个历史失败与 AR019 同因（git-stash 对照
  验证，与本 AR 无关，不纳入门禁）。**decision=keep**。
- **T9**：README——5.23 章节插入 5.22 与 EX001 之间（EX001 顺延 5.24，
  目录无编号行不受影响）、5.1 结果表（补 AR020 缺行 + AR022 去「最终」+
  AR023 行）、5.6 回退记录、AR 演进表（补 AR022 缺行 + AR023）、
  版本表 v4.12、标题/徽章 211、快速开始（166→211 + ar023 两命令 +
  3 个缺失测试文件）、目录树（214 项 = 211 过 + 3 skip）、头部 tagline；
  `docs/images/cover.jpg` 重生成（v4.12 优惠券主题，76KB 单提交推送）；
  `docs/REPRODUCTION.md` 命令 27/28、outputs/ar023、3.2 矩阵表（补
  AR021–AR023 行）、3.2.16 回退表；BACKLOG B05 毕业行。
- **T10**：devflow-review 自查见下；`git mv specs/changes/AR023-…
  specs/archive/`。
- **T11**：gitee worktree 增量同步（每包 ≤50KB）；收尾
  `git fetch gitee && git diff -w --stat gitee/main main` 为空。
  实测：5 个增量提交逐个推送——`ed74de7`（核心 9 模块）→
  `ff4e8c2`（测试+探针+评测）→ `eb15e58`（文档+归档 spec）→
  `3b7d00c`（封面 76KB 单独小包）→ 本提交（T11 记录）；
  收尾校验 diff 为空，远端 HEAD 见本行更新后的最后一次推送。

## devflow-review 独立自查（findings + verdict）

按 devflow-review 标准对 spec/代码/评测产物做独立复查：

**Findings：**
1. *SRS↔实现一致性*：FR1–FR6 逐条对应实现（PROMOS 常量、/api/promos、
   /promo/claim、v1+v2 领取按钮、权威折扣结算、快照字段、成功页实付行；
   规划器 7 条后处理规则全部有对应单测）——无缺口。
2. *代码异味*：`plan_instruction` 后处理在基础编译之后、`_compile_base`
   内部零改动（回归面最小化，189 基线全绿实证）；frozen dataclass 用
   `dataclasses.replace` 保持不可变语义；谓词/提示/技能名全部从同一
   `PROMOS` 常量派生，无三处手写漂移。无直接状态变异、无散落的重复逻辑。
3. *测试充分性*：22 项全部真实执行（无 mock）——规划器可行/不可行/回归、
   验证器真实 state 形状（含 code 不匹配/贴线 False/无 promo 三反例）、
   分解继承、技能字段级回归（无码路径与旧 4 步逐字段一致）、真实 HTTP
   全流程双布局、贴线不消耗 + 同券复用、真实 Edge 0 LLM 链。
4. *门禁完整性*：211 passed（189 基线零回退）+ AR011 30/30 0 LLM，
   均为真实命令输出（P5 门禁块，rc=0）。
5. *数据真实性*：改动前证据来自旧代码真实执行（404、4 字段订单、
   4 步技能、无谓词）；改动后指标全部出自 `outputs/ar023/eval/`；
   P4 naive 对照使用探针捕获的旧代码真实订单（¥598 无折扣）。
   无随机数、无硬编码结果。
6. *已知边界（如实记录，不回避）*：券面为服务端常量两档（动态发券、
   多券组合、券过期不在本期，SRS §5 已声明）；同步 XHR 领取在现代
   浏览器控制台有弃用告警——为换取「领取先于提交订单的确定性」而保留，
   README §5.23 已说明理由与实测否决的 303 方案。
7. *文档一致性*：README 5.23 位于 EX001（5.24）之前；5.1/5.6/演进/
   版本/快速开始/目录树/徽章与真实数字一致（211/8-8/3-3/0 LLM/
   50-150）；AR022 在 5.1 与演进表的缺行已补。

**Verdict：pass（保留，keep）**——组合优于现状（规划 8/8 vs naive 0/8；
执行 3/3 0 LLM 且服务端权威确认；全部门禁不回退），无回退触发条件。
