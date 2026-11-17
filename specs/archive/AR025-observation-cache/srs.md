# [AR025] 自适应观测缓存与单往返快照（adaptive observation cache）

| 字段 | 内容 |
|------|------|
| AR 编号 | AR025 |
| AR 主题 | adaptive-observation-cache |
| 关联 SR | BACKLOG B08（观测缓存与增量 DOM diff） |
| 日期 | 2026-11-16 |
| 状态 | Draft |

## 1. 背景与目标

AR011–AR024 的端侧运行时在每一个技能动作后都调用 `BrowserEnv.observe()`。
旧实现一次 observe 触发 **4 次浏览器往返**：元素扫描 JS、`inner_text("body")`、
`GET /api/state`、`title()`。真实基线（`scripts/tmp_ar025_probe.py`，AR011 30 场景、
真实 Edge、0 LLM）测得：

- observe **440 次**，总耗时 **11.13s**；
- 相邻两次快照完全一致 **125 次（28.4%）**——这些调用纯属重复提取；
- 技能层还存在“最后一步已 observe，返回后再次 observe”的冗余。

目标（BACKLOG B08）：在不改变任何动作语义、验证器口径和 30 场景成功率的前提下，
把观测路径改为**单往返快照 + 修订号缓存**：DOM 未变时复用元素表/文本，权威
server state 仍每次实时读取；并让技能层复用最后一份观测。要求真实可测、0 mock。

## 2. 范围

**In Scope：**
- `step_rl/edge/browser.py`：页面初始化注入 MutationObserver 修订号；
  新增单往返快照 JS；`observe()` 增加缓存、命中/未命中统计与往返计数；
- `step_rl/edge/skill_library.py`：`run_skill` 接收已有观测、返回末次观测；
  `run_skill_hierarchy` 复用末次观测，删除冗余 observe；
- `tests/test_edge_observation_cache.py`：真实 Edge/真实 HTTP 测试；
- `scripts/ar025_baseline_probe.py`、`scripts/ar025_eval.py`；
- README / REPRODUCTION / 封面 / BACKLOG / 归档 / Gitee。

**Out of Scope：** 站点 DOM 结构变更（B06 v3）、跨进程缓存、LLM 训练、并发模型、
任何 mock 或伪造指标。AR024 的线程安全与原子持久化语义保持不变。

## 3. 功能需求

### FR1 单往返观测快照
**描述：** 一次完整 observe 只发起一次 `page.evaluate` 往返。
**期望行为：** JS 返回 `{elements, text, title, state, rev, doc, url}` 中的
DOM 部分；Python 侧只做排序/截断；权威 state 通过同一 evaluate 内的
`fetch('/api/state')` 取得。
**验收：** 真实 Edge 上完整快照的 roundtrip 计数为 1（不含缓存探测），
元素字段与旧 `_OBSERVE_JS` 逐字段一致。

### FR2 修订号缓存
**描述：** 缓存键为 `(doc_id, url, rev, title)`；未变时复用元素表与 body 文本。
**触发条件：** 连续 observe 之间无 DOM 变化（如技能末次重复观测、wait/scroll）。
**期望行为：** 命中时只做一次轻量 meta evaluate（rev/doc/url/title + 实时 state），
返回缓存元素与文本；命中/未命中计数可审计。
**异常处理：** meta 失败、doc/url 变化、type 动作（value 属性不触发 DOM mutation）
一律视为未命中并重新扫描；绝不返回过期元素。
**验收：** 真实页面点击/导航后 rev 变化并重新扫描；纯 wait/duplicate observe 命中；
缓存命中时服务端 state 仍实时刷新。

### FR3 技能层观测复用
**描述：** 技能执行不再重复观测。
**期望行为：** `run_skill(initial_obs=...)` 使用调用方已有观测；返回末次观测；
`run_skill_hierarchy` 直接用其做进度判定和 LLM fallback 的 `initial_obs`。
**验收：** 30 场景 skill_steps 仍为 276、policy_steps=0、success=30/30；
observe 调用数低于基线。

### FR4 可审计指标
**描述：** `env.observation_metrics` 暴露 `calls/hits/misses/dom_scans/roundtrips/seconds`。
**验收：** 评测 JSON 写入真实计数；README 只引用该 JSON。

## 4. 非功能需求

| 类型 | 指标 | 要求 |
|------|------|------|
| 成功率 | AR011 30 场景 | 30/30，0 LLM，零回退 |
| 观测开销 | observe 浏览器往返 | 相对基线下降 ≥50% |
| 观测耗时 | observe 总耗时 | 相对基线下降 ≥25% |
| 正确性 | 缓存命中后 state | 必须来自本次实时 `/api/state` |
| 兼容性 | AR021/AR024 审计 JSON | 形状与语义不变 |

## 5. 约束与假设

- 只用系统 Edge（`channel="msedge"`）与真实 `LocalShopServer`；
- 修订号由页面内 MutationObserver 维护，导航后由 init script 重新建立；
- 缓存只在单 `BrowserEnv` 内生效，不跨会话共享；
- 任何无法证明未过期的场景默认未命中，正确性优先于命中率。

## 6. 术语

| 术语 | 定义 |
|------|------|
| 修订号 rev | 当前 document 内非 `data-eid` DOM mutation 的单调计数 |
| 单往返快照 | 一次 Playwright evaluate 返回元素、文本、标题、服务端 state |
| AOC | Adaptive Observation Cache，AR025 的观测缓存层 |
