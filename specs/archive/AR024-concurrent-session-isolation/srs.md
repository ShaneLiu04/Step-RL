# [AR024] 并发会话隔离压测（concurrent session isolation）需求设计说明书

## 1. 背景与目标

AR011–AR023 的全部评测都是**单会话串行**的：一个进程内一个
`BrowserEnv`、一个任务、一次运行。端侧运行时一旦以多会话方式服务
（同一进程内多个真实 Edge 会话并发跑各自的任务），进程内共享的
**技能运行时组件**就成了串扰面。代码审计定位到四处共享状态均无
并发保证：

1. **技能统计计数丢失**：`skill_stats._STATS` 是模块级全局字典，
   `record_skill_outcome` 对 `attempts/successes/failures` 做
   非原子读-改-写——并发会话的成功/失败留痕可能互相吞掉；
2. **跨租户统计静默擦除**：`load_skill_stats`/`from_dict` 先
   `clear()` 再逐项插入，一次并发的「恢复/重载」可以把其他会话
   已留痕的成败**整段抹掉**，且中间态可被读方看到；
3. **非原子持久化**：`save_skill_stats` / `save_induced_skills`
   直接 `open("w")` 写同一文件——并发保存交错可产出**解析失败的
   JSON**，或 last-writer-wins 静默丢掉另一方的完整快照；
4. **注册表 upsert 竞态**：`register_induced_skill` 先查后追加
   （check-then-append）——并发注册同名技能可产生**重复候选**，
   干扰 AR021 的按成功率选择规则。

服务端 `SessionStore` 本身带锁且按 `sid` 键控——改动前基线探针
（`scripts/ar024_baseline_probe.py`，旧代码真实执行，
`outputs/ar024/baseline_probe.json`）将同时实测：(a) 上述四处
缺陷在旧代码上的真实数字（丢计数、损坏/丢失文件、重复候选），
(b) 2 个真实并发 Edge 会话在服务端状态下**无串扰**——证明隔离
缺口在进程共享的技能运行时层，而非服务端会话层。

目标（BACKLOG B07）：多会话并发成为**受验证的运行模式**——

- 4 个并发真实 Edge 会话（共享一个真实服务端）各跑不同任务，
  **4/4 成功、互不串扰**（每会话的服务端状态快照与自身任务精确
  一致）、0 LLM；
- 并发失败留痕**精确**：4 次并发的真实 DOM 失败 → 统计恰好
  4/4（不丢一次）、淘汰判定一致、审计 JSON 完整可解析；
- 并发持久化**无损**：并发保存后文件恒可解析且等于某一方快照；
- 串行语义**零变化**：既有 211 项 edge 测试与 AR011 30 场景
  （0 LLM）全部不回退。

## 2. 范围

- `step_rl/edge/skill_stats.py`：模块级锁；`record_skill_outcome` /
  `from_dict` / `reset_skill_stats` / `clear_skill_stats` 原子化；
  `save_skill_stats` 一致快照 + 原子文件写；`load_skill_stats`
  先解析后在锁内替换（纯行为加固，既有签名与 JSON 形状不变）；
- `step_rl/edge/skill_library.py`：模块级锁；`register_induced_skill`
  upsert 原子化；`save_induced_skills` 一致快照 + 原子写；
  `load_induced_skills` 先解析后注册（纯行为加固）；
- `step_rl/edge/concurrency.py`（**新模块**）：`atomic_write_json`
  （同目录临时文件 + `os.replace`）、`run_concurrent`
  （多线程 asyncio 多会话执行器，逐任务隔离异常）；
- 评测 `scripts/ar024_eval.py`（真实 Edge / 真实服务端 / 0 LLM）
  与改动前基线探针 `scripts/ar024_baseline_probe.py`；
- 单测 `tests/test_edge_concurrency.py`；
- 不在范围：v3 布局（B06）、观测缓存（B08）、B03 剩余的长度平局
  裁决、多进程/多机部署（本 AR 边界为**单进程多会话**；跨进程仍
  依赖文件锁或单写者约定，超出本 AR）、LLM 兜底并发（本 AR 能力链
  全程技能路径覆盖，0 LLM）；不训练新模型；不修改
  AR001–AR023 已归档内容。

## 3. 功能需求

### FR1 技能统计线程安全（`skill_stats.py`）

- 模块级 `threading.Lock` 覆盖：`record_skill_outcome` 的读-改-写
  全程、`from_dict` 的 clear+重建、`reset_skill_stats`、
  `clear_skill_stats`、`save_skill_stats` 的快照读取；
- `record_skill_outcome` 并发执行不丢更新：N 线程 × M 次成功记录
  → `attempts == successes == N*M`，精确；
- `from_dict` 原子替换：并发「记录 + 重载」的终态必为某个**总序**
  下的一致快照（不出现清了一半、插了一半的交错态）；
- `save_skill_stats` 写入为同目录临时文件 + `os.replace`，并发保存
  后文件恒可解析且等于某一方的一致快照；
- 既有函数签名、`SkillStat` 字段、审计 JSON 形状**逐字段不变**
  （AR021 测试与产物继续可读可写）。

### FR2 技能注册表线程安全（`skill_library.py`）

- 模块级锁覆盖 `register_induced_skill` 的「查名 → 替换/追加」
  全程与 `clear_induced_skills`；
- 并发以同名注册同一 operation：终态恰好 **1 个候选**（不重复）；
- `save_induced_skills` 在锁内取一致快照后原子写；
  `load_induced_skills` 先完整解析文件再逐项注册；
- `_INDUCED` 的 JSON 形状、`_select_best` 选择规则、
  `itertools.count` 顺序号语义**不变**（AR019/AR020/AR021 行为
  零漂移）。

### FR3 多会话运行时原语（`concurrency.py`，新模块）

- `atomic_write_json(path, data)`：同目录临时文件 + `os.replace`，
  失败时不留下半成品文件；
- `run_concurrent(coros)`：每个协程一个独立线程 + 独立
  `asyncio.run` 事件循环，并发执行、按输入序返回结果；单任务异常
  只隔离到该任务（其余任务完成），不拖垮整组；
- 只依赖标准库，不引入第三方并发组件。

### FR4 真实并发隔离评测（`scripts/ar024_eval.py`）

- P0 改动后复核：锁/原子写存在性 + 单会话串行行为对照（0 LLM）；
- P1 **4 并发真实 Edge 会话**（共享 1 个 `LocalShopServer`，
  barrier 同步起跑）：S1 加购 p3×2、S2 加购 p4 + 结算、
  S3 移除 p3（加载 AR021 持久化 remove 模板）、S4 数量改 p3=3
  （seed p3×2）——**4/4 成功、0 LLM**；结束后逐会话
  `/api/state` 快照断言互不串扰（S1 cart={p3:2}、S2 订单含且仅含
  p4、S3 cart 空、S4 cart={p3:3}）；记录并发墙钟与串行对照；
- P2 **并发失败留痕**：注入失效 remove 模板为唯一候选，4 会话
  barrier 并发执行 → 4 次真实 DOM 失败 → 统计**恰好**
  attempts=4/failures=4、demoted、审计 JSON 可解析；
- P3 **并发持久化**：8 线程 × 多轮不同快照的
  `from_dict`+`save_skill_stats` 与注册表并发保存 → 每轮文件可
  解析、终态等于某一方快照；
- P5 组合门禁：edge 套件 + AR011 30 场景（30/30、0 LLM）。

### FR5 改动前基线探针（`scripts/ar024_baseline_probe.py`，旧代码留证）

- E1 统计丢更新（降低调度切换间隔放大竞态窗口后实测）；
- E2 并发保存交错（损坏/丢失计数）；
- E3 同名 upsert 重复候选；
- E4 **2 真实并发 Edge 会话**（共享服务端）：证明服务端状态无
  串扰（隔离缺口定位在服务端之外的共享运行时层）。

### FR6 单测（`tests/test_edge_concurrency.py`）

- 无丢更新（8×50 成功/失败各一组，精确断言）；
- 并发保存可解析性 + 快照一致性；
- 同名并发 upsert 恰好 1 候选；
- `from_dict`/`record` 并发的终态一致性不变量；
- `atomic_write_json` / `run_concurrent` 行为（含异常隔离与
  并发性墙钟断言）；
- 串行回归：锁不改变单线程语义（register→record→save/load 往返）。

### FR7 文档

- README 新增 5.24 节（动机/机制对照表/P0–P5 真实评测表/效率对照/
  兼容性边界/复现命令），EX001 顺延 5.25；5.1 结果表、5.6 组合
  回退记录、AR 演进表、版本表（v4.13）、快速开始、目录树、tests
  徽章、REPRODUCTION.md 同步；BACKLOG B07 毕业记录。

## 4. 非功能

- 串行路径零性能回退：单会话技能执行耗时与既有评测同量级
  （P4 对照）；锁开销只在多会话并发时出现；
- 所有指标来自真实执行日志（`outputs/ar024/**`），禁止 mock；
- 失败显式：探针/评测任一断言失败即非零退出码，不静默降级。

## 5. 假设

- 单进程多会话是本 AR 边界；同一进程内多个「恢复统计」调用方共享
  一个 `_STATS`（服务级技能库语义），「load = 原子替换」为文档化
  语义（后到者胜），不合并历史内存；
- Windows `os.replace` 对同目录目标原子（`MoveFileEx` 替换）；
- 4 个并发 headless Edge 实例在评测机资源内可稳定运行。

## 6. 术语

- **串扰（crosstalk）**：会话 A 的动作/状态出现在会话 B 的服务端
  快照或技能留痕中；
- **总序**：并发操作的某种串行化次序；终态等于按该次序依次应用
  的结果即视为一致；
- **原子替换**：`from_dict` 以「清空 + 重建」在同一临界区内完成，
  读方只能看到替换前或替换后的完整快照。
