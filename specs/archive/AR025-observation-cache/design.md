# [AR025] 增量实现设计

## 1. 总体思路

不改变动作、技能、验证器和成功判定，只重构“读页面”这一层：

1. 页面启动时注入 MutationObserver，维护 `__steprl_rev` 与 `__steprl_doc`；
2. `observe()` 先发一次轻量 meta 请求（rev/doc/url/title + 实时 `/api/state`）；
3. meta 与缓存键一致 → 复用缓存的元素表/body 文本；否则再发一次 DOM 扫描；
4. 技能层把已有观测传入 `run_skill`，并直接复用其末次观测，删除重复 observe。

旧实现每次 observe 4 次往返（elements、inner_text、state、title）；新实现
未命中 2 次、命中 1 次。基线实测相邻重复占 28.4%，再加上技能层冗余观测，
可获得可审计的往返/耗时下降。

## 2. 模块改动

### 2.1 `browser.py`

- `_OBSERVER_JS`（init script）：每个 document 分配随机 `doc`，监听
  `childList/characterData/attributes`；忽略 `data-eid` 自身写入，rev 单调递增。
- `_META_JS`：返回 `{rev, doc, url, title, state}`，其中 state 由页面内
  `fetch('/api/state')` 实时读取；失败返回 `{}`。
- `_DOM_JS`：返回 `{elements, text}`。字段与旧 `_OBSERVE_JS` 完全一致，
  仍写入 `data-eid`；文本截断 600。
- `observe()`：
  - 发 meta；`key=(doc,url,rev,title)`；
  - 命中：`deepcopy` 缓存元素/文本，state 用本次 meta；
  - 未命中：发 DOM 扫描，排序/截断后写缓存；
  - `observation_metrics` 记录 `calls/hits/misses/dom_scans/roundtrips/seconds`。
- `execute()` 对 `type` 主动失效缓存（HTML `value` 属性不触发 mutation，
  但语义值已变）；`reset()` 清空缓存。
- `observe(force=False)` 可强制未命中；默认不强制。

### 2.2 `skill_library.py`

- `run_skill(env, skill, initial_obs=None)`：有 initial_obs 则跳过首次 observe；
  末次观测放入 `SkillResult.observation`。
- `run_skill_hierarchy`：把 reset/上次观测传给 run_skill；技能成功后直接用
  `result.observation` 做 `compute_progress`，不再额外 observe；
  失败时以该观测作为 LLM rollout 的 `initial_obs`。

## 3. 关键决策

- **D1 缓存键含 doc/url/rev/title**：导航、pushState、标题变化都失效；
  换页后 init script 重新分配 doc，绝不跨页复用。
- **D2 state 永不缓存**：每次 observe 实时 `fetch('/api/state')`，验证器口径
  不因缓存改变；这是与“缓存整个 observation”最关键的安全边界。
- **D3 type 主动失效**：DOM mutation 不可见 value property，否则会读到旧输入值。
- **D4 正确性优先**：任何 meta 异常、键缺失、force 都走完整扫描；命中率仅作优化。
- **D5 单 env 私有缓存**：不共享、不加全局锁，与 AR024 多会话模型正交。

## 4. 测试设计（真实 Edge / 真实 HTTP）

1. 初始 observe 后 metrics：calls=1、dom_scans=1、roundtrips=2；
2. 连续第二次 observe：hit=1，元素表相等，state 仍实时；
3. 点击真实商品链接后 rev 变化：未命中并扫描，URL/元素更新；
4. 导航后 doc 变化，不跨页复用；
5. `type` 后缓存失效，value 读取为新值；
6. `force=True` 强制扫描；
7. 技能层：`run_skill(initial_obs=...)` 不增加首次 observe；
8. 30 场景回归由 P1 主评测覆盖。

## 5. 风险与对策

| 风险 | 对策 |
|------|------|
| MutationObserver 漏掉 value 变化 | type 动作主动失效；测试 5 |
| 跨页 doc_id 重用 | 每 document 随机 doc + URL 键；测试 4 |
| 缓存命中读到过期 state | state 永不缓存；每次实时 fetch |
| 技能层复用观测导致进度误判 | 只用同一次动作后的末次观测；P1 30/30 验证 |
| 往返减少但总耗时不变 | 同时记录 roundtrips 与 seconds，P3 对照 |

## 6. 回滚

- 回退 AR025 提交：删除缓存/快照 JS，恢复旧 `_OBSERVE_JS` 与技能层 observe；
- 产物保留在 `outputs/ar025/`；不影响 AR021/AR024 持久化形状。

## 7. 组合回退规则

A = 当前最优 AR024（edge 158 passed + 全量 237 passed/10 代理失败/3 skip + AR011 30/30 0 LLM）。
1. B = A + AR025 代码；edge 套件不得新增失败。
2. B 的 AR011 30 场景必须 30/30、policy_steps=0、prompt_tokens=0。
3. B 的 observe 往返下降 ≥50% 且耗时下降 ≥25%；否则回退并归档负结果。
4. 全部满足 → 保留 B，README v4.14 记录真实数字。
