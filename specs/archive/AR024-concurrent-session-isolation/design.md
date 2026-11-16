# [AR024] 增量实现设计

## 1. 总体思路

不新增运行时分叉、不改任何既有签名：给进程共享的技能运行时组件
（`skill_stats._STATS` / `skill_library._INDUCED` + 两处 JSON
持久化）补上**锁 + 原子写**，并把「多会话并发执行」收敛为一个
可复用的标准库原语（`concurrency.run_concurrent`），用真实
4 并发 Edge 会话把隔离与留痕精度**实测**出来。服务端
`SessionStore` 已有锁且按 `sid` 键控，本 AR 不动它——探针 E4
证明服务端层无串扰，改动面严格限于共享运行时组件。

## 2. 模块改动

### 2.1 `skill_stats.py`（行为加固）

- 新增模块级 `_LOCK = threading.Lock()`；
- `record_skill_outcome`：整个「取/建 stat → 计数更新 → 淘汰判定」
  包进 `with _LOCK:`；
- `from_dict`：`with _LOCK:` 内先建好完整新字典再
  `_STATS.clear(); _STATS.update(new)`——一次临界区内的原子替换，
  读方只看到替换前或替换后的完整快照；
- `reset_skill_stats` / `clear_skill_stats`：`with _LOCK:`；
- `save_skill_stats`：`with _LOCK:` 内取 `to_dict()` 一致快照，
  锁外调用 `concurrency.atomic_write_json`（同目录临时文件 +
  `os.replace`）；
- `load_skill_stats`：先 `json.load` 完整解析（锁外 I/O），再
  `from_dict`（锁内替换）——解析失败不会碰内存态。

### 2.2 `skill_library.py`（行为加固）

- 新增模块级 `_LOCK = threading.Lock()`；
- `register_induced_skill`：「按名查找 → 替换/追加」全程
  `with _LOCK:`（upsert 原子化，同名并发注册恰好 1 候选）；
- `clear_induced_skills`：`with _LOCK:`；
- `save_induced_skills`：`with _LOCK:` 内遍历 `_INDUCED` +
  `_select_best`（其 `is_demoted` 读取也在锁内一致）构建快照，
  锁外 `atomic_write_json`；
- `load_induced_skills`：先完整 `json.load` 再逐项
  `register_induced_skill`（每项自带锁）。

### 2.3 `concurrency.py`（新模块，标准库 only）

- `atomic_write_json(path, data)`：`tempfile.NamedTemporaryFile`
  与目标同目录（`dir=` 目标目录、`delete=False`）写完整 JSON，
  `os.replace(tmp, path)`；异常时删除临时文件、原文件不动；
- `run_concurrent(coros, name_prefix="session")`：
  - 每个协程 → 一个 `threading.Thread`，线程内
    `asyncio.run(coro)`；
  - 结果按输入序存入 `list`（`results[i]`）；
  - 单任务异常记为 `{"error": "Type: msg"}` 存入该槽位，其余任务
    不受影响；全部 `join` 后返回；
  - 返回 `(results, wall_seconds)`——`wall_seconds` 用于
    「并发墙钟 ≈ max(单会话) 而非 sum」的并行性证据。

### 2.4 `scripts/ar024_baseline_probe.py`（改动前执行，旧代码留证）

- E1 丢更新：`sys.setswitchinterval(1e-6)` 放大调度切换，
  barrier 同步后 8 线程 × 250 次 `record_skill_outcome(..., True)`，
  报告 `attempts`（期望 2000，旧代码 <2000）；
- E2 保存交错：8 线程 × 10 轮，每轮各线程 `from_dict(snapshot_i)`
  后 `save_skill_stats(同一路径)`；主线程每轮检查文件可解析性与
  「等于某一方快照」，累计损坏/丢失计数；
- E3 upsert 重复：4 线程 × 200 轮，每轮以不同名
  `dup_{r}` 并发 `register_induced_skill`；报告候选总数 vs 不同名
  数（旧代码 总数 > 不同名）；
- E4 服务端隔离对照：1 个 `LocalShopServer` + 2 个真实并发
  `BrowserEnv`（A 加 p3×2 / B 加 p4×1，barrier 起跑），逐会话
  `/api/state` 快照——预期**无串扰**（定位缺口不在服务端）。
- 全部结果写 `outputs/ar024/baseline_probe.json`，非零退出码当且
  仅当断言层失败（E1–E3 的缺陷存在是**预期**，不算失败）。

### 2.5 `scripts/ar024_eval.py`（改动后主评测，真实 Edge / 0 LLM）

- 公共 harness：1 个共享 `LocalShopServer` + N 个
  `BrowserEnv`（各自 `channel="msedge"`、独立 Edge 实例）；
  每会话 `run_concurrent` 工作线程内 `asyncio.run`；
- P0 复核：`threading` 锁存在（导入断言）、`atomic_write_json`
  往返、单会话串行「买两件无线充电器」0 LLM（对照基线行为）；
- P1 四会话并发（barrier 起跑，`threading.Barrier(4)` 置于各
  会话 `env.start()` 完成后、首个动作前）：
  - S1 「买两件无线充电器」→ add_item p3×2；
  - S2 「买一件蓝牙降噪耳机并结算」→ add_item p4 + checkout；
  - S3 「把购物车中的无线充电器移除」→ 先
    `load_induced_skills(outputs/ar021/eval/induced_skills.json)`
    （复用 AR021 持久化产物），seed {p3:2}；
  - S4 「把购物车中的无线充电器数量改为3」→ update_quantity，
    seed {p3:2}；
  - 断言：4/4 `run_task(..., model=None, ...)` 成功、
    `policy_steps==0`；逐会话 `env.get_state()` 快照精确相等
    （S1 {p3:2} / S2 订单仅 p4 且 cart 空 / S3 cart 空 / S4 {p3:3}）
    ——**互不串扰的逐会话证据**；
  - 记录 `wall_seconds`（run_concurrent）与逐会话耗时 →
    并发/串行对照；
- P2 并发失败留痕：`clear_induced_skills` + 注入
  `STALE_TEMPLATE`（「删除 {product}」按钮，站点实际渲染
  「移除 {product}」，AR021 同款真实 DOM 失败）为 operation
  `remove` 唯一候选；4 会话各自 seed {p3:1}、barrier 并发跑
  「把购物车中的无线充电器移除」→ 4 次真实失败 + 4 次并发
  `record_skill_outcome`；断言 `attempts==4`、`failures==4`、
  `demoted==True`、`save_skill_stats` 后可解析；
- P3 并发持久化：8 线程 × 10 轮，各线程不同已知快照的
  `from_dict` + `save_skill_stats`，外加 4 线程并发
  `save_induced_skills`；主线程逐轮校验可解析性，终态等于某一方
  快照；
- P4 串行回归：单会话「买两件无线充电器」+「数量改为 3」连续两
  任务 0 LLM，记录耗时（对照 P1 单会话耗时同量级）；
- 产物：`outputs/ar024/eval/{ar024_results.json, ar024_report.md,
  skill_stats.json, induced_skills.json}`。

## 3. 关键设计决策

- **D1 锁粒度**：per-module 单锁（`_STATS` / `_INDUCED` 各一把）。
  临界区只覆盖内存读-改-写与快照构建，**锁内不做 I/O**（I/O 在
  锁外走原子文件写）——避免锁内阻塞放大串行路径延迟（FR 非功能）。
- **D2 load 语义 = 原子替换（后到者胜）**：不做跨调用方合并。
  服务级技能库是单一事实源；「恢复审计文件」的文档化语义就是
  替换内存态。旧代码的缺陷不是「不替换」，而是替换**非原子**
  （clear 与 insert 之间可被插队）。
- **D3 原子写 = 同目录临时文件 + `os.replace`**：Windows 上
  `os.replace` 走 `MoveFileEx(REPLACE_EXISTING)`，对读者要么看到
  旧文件要么看到新文件；临时文件与目标同目录保证同一文件系统
  （跨目录 rename 非原子）。
- **D4 upsert 原子化而非换数据结构**：`dict[name]` 天然去重但
  会丢「多候选并存」（AR021 语义），故保留 list + 锁内查重，
  JSON 形状与 AR021 逐字段一致。
- **D5 线程模型 = 每会话一线程一事件循环**：Playwright async
  与 asyncio 事件循环不跨线程共享；每线程 `asyncio.run` 自带
  独立 driver 会话，4 个 Edge 实例天然隔离（cookie jar / context
  互不相通）——隔离性由浏览器层 + 服务端 sid 双重保证，共享的
  只剩技能运行时组件（正是本 AR 加固面）。

## 4. 测试设计（`tests/test_edge_concurrency.py`，12 项）

1. 无丢更新（成功）：8 线程 × 50 次 → `attempts==successes==400`；
2. 无丢更新（失败）：8 线程 × 50 次 → `attempts==failures==400`、
   `demoted==True`；
3. 并发保存可解析：8 线程 × 6 轮不同快照 from_dict+save →
   终文件可解析且等于某一方快照；
4. 同名并发 upsert：4 线程 × 50 轮（轮内同名）→ 恰好 1 候选；
5. `from_dict` 原子替换：单线程 record→load→record 总序语义
   （load 抹掉首条记录、保留第二条，`attempts==1`）；
6. `record` 与 `from_dict` 并发不变量：2 线程 barrier 并发
   20 轮后，`get_skill_stat` 可见态必为「仅文件项」或「文件项 +
   x 的某一致计数」，且 `x` 不存在于文件却计数为 0 的撕裂态
   不出现；
7. `atomic_write_json`：往返一致 + 并发 4 写者 × 20 轮文件恒
   可解析且等于某写者 payload；
8. `run_concurrent` 结果按序 + 异常隔离（1/4 抛错，其余 3 完成，
   错误槽位带类型信息）；
9. `run_concurrent` 并行性：4 个 0.2s 睡眠协程墙钟 < 0.8s；
10. 串行往返：register→record(success/failure)→save→clear→load →
    统计与注册表逐字段恢复（AR021 语义零漂移）；
11. `save_induced_skills` 并发：4 线程并发保存 → 文件可解析、
    形状合法（operation → {name, steps}）；
12. 锁不改变单线程选择规则：注入两候选（1 淘汰）→
    `_select_best` 选未淘汰者（与 AR021 测试同断言，串行对照）。

## 5. 风险与对策

| 风险 | 对策 |
|------|------|
| 锁内误入 I/O 拖慢串行路径 | 代码评审 + P4 单会话耗时对照（与既有评测同量级） |
| `from_dict` 替换语义与旧调用方假设不符 | 全仓 grep `load_skill_stats/from_dict` 调用点（仅评测/测试）；文档化「后到者胜」；既有测试全绿 |
| Windows `os.replace` 语义差异 | 目标与临时文件同目录；单测 7 固化；损坏文件场景由 P3 实测覆盖 |
| 4 并发 Edge 启动抖动（偶发 launch 慢/失败） | 每会话独立 try/finally 关闭；评测失败显式退出码；重跑留多份 results（不覆盖历史） |
| E1 竞态窗口太小、旧代码探针不复现 | 探针内 `sys.setswitchinterval(1e-6)` 放大切换 + barrier 同步 + 足够迭代数；新代码下锁消除窗口，同参数精确 400/2000 |
| `run_concurrent` 线程泄漏 | 全部 `join` 后返回；每线程 finally 关闭事件循环；测试断言无存活线程 |
| 评测机内存（4× Edge ≈ 数 GB） | 串行评测惯例 headless；P1/P2 复用同一组 4 env，不叠加第 5–8 个浏览器 |

## 6. 回滚

- 代码：`git revert` 本 AR 提交（skill_stats/skill_library 还原 +
  concurrency.py/评测/单测移除）；
- 运行态：无需（锁与原子写不改变任何持久化形状；既有
  induced_skills.json / skill_stats.json 原样可读）；
- 已归档产物不动。

## 9.1 组合回退规则（沿用 AR001 design §9.1）

以 **A = 当前最优（AR023 状态：edge 211 passed + 3 skipped；
AR011 30/30、0 LLM；AR023 规划 8/8 + 执行 3/3、0 LLM）** 为
初始最优。

1. B = A + 本 AR 加固（无真实执行）：B 的 edge 套件必须
   ≥211 passed 且 0 failed（既有测试零回退）；不满足 → 回退 B；
2. B 的 P1（4 并发真实 Edge）任一会话串扰或失败、或 P2 留痕
   不精确（≠4/4）、或 P3 出现不可解析文件 → 组合失败，回退并
   归档负结果（`outputs/ar024/**` 全部保留）；
3. B 的 AR011 30 场景必须 30/30 且 0 LLM（串行语义零漂移的
   组合级证据）；不满足 → 回退；
4. 全部满足 → 保留 B，A 更新为 B；README 5.24 + 5.6 记录
   保留决策与真实数字。
