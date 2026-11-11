# [AR019] 需求设计说明书

| 字段 | 内容 |
|------|------|
| AR 编号 | AR019 |
| AR 主题 | skill-induction（失败驱动的技能自动归纳） |
| 日期 | 2026-11-11 |
| 状态 | Draft |

## 1. 背景与目标

AR010 的技能来自真实专家演示的**人工**参数化；AR015 扩展技能库同样依赖手工
编写。当前运行时的闭环有一个缺口：

> 能力门控（AR012）发现未覆盖任务 → 拒绝执行或回退 LLM → **兜底成功的
> 轨迹被直接丢弃** → 同类任务下次仍要付出一次 LLM 成本。

AR019 补上最后一环：**失败驱动（能力缺口驱动）的技能自动归纳**。

- 兜底 LLM 在真实浏览器上成功完成任务后，轨迹（动作 + 语义元素元数据）被
  记录；
- 归纳器把轨迹泛化为**参数化技能模板**（商品名 → `{product}`，目标数量 →
  `{qty}`）；
- 模板注册进技能库并持久化到 JSON；
- 此后同类任务命中能力门控，**0 LLM、0 prompt tokens** 直接执行。

目标：

1. 归纳前：`remove` 类指令能力门控判定 **未覆盖**（真实缺口证据）；
2. LLM 兜底真实完成移除任务（真实 GPU 推理）；
3. 归纳 + 注册后：同任务、跨商品（p4）、跨布局（v2）技能路径 3/3，0 LLM；
4. 组合门禁：30 场景统一套件不回退（≥ 30/30），全量单测通过。

不达标即按 design.md §9.1 回退。

## 2. 范围

**In：**

- 服务端真实 `/remove/{pid}` 路由与购物车「移除」按钮（v1/v2）；
- 验证器新谓词 `cart_without`（购物车中目标商品数量为 0）；
- 规划器解析「移除/删除 …」指令 → `operation="remove"` TaskSpec；
- 新模块 `skill_induction.py`：`TrajectoryRecorder`（真实轨迹记录）+ 
  `induce_skill`（模板泛化）；
- 技能库诱导技能注册表 + JSON 持久化/加载；
- `scripts/ar019_eval.py` 真实评测（GPU LLM 兜底 → 归纳 → 复用 → 迁移）；
- 单测、报告、README、复现文档、gitee 同步。

**Out：**

- 新模型训练（复用 AR004 适配器做兜底）；
- 修改既有 add/update/checkout 技能语义；
- 公网站点。

## 3. 功能需求

### FR1 服务端移除能力

- `GET /remove/{pid}`：从会话购物车删除该商品并重定向回 `/cart`；
- v1/v2 购物车每行新增真实按钮，`aria-label='移除 {商品名}'`；
- 非法商品返回 400 错误页。

### FR2 验证器谓词

- `cart_without`：`all(cart.get(pid,0) == 0 for pid in task.targets)`；
- 只读真实服务端 `/api/state`，成功判定不信任模型自述。

### FR3 规划器

- 指令含「移除/删除」且命中商品 → `operation="remove"`、
  `predicates=["cart_without"]`、`start_path="/cart"`、`seed_cart` 预置
  待删商品；
- 不命中商品 → 维持 `planner_unsupported`。

### FR4 轨迹记录

- `TrajectoryRecorder` 包装真实 `BrowserEnv`：
  - `observe()` 缓存当前语义元素表（eid → role + accessible_name）；
  - `execute()` 在真实执行前把动作解析为 (kind, role, name, value, url)；
  - 全部动作真实执行，不拦截、不注入。

### FR5 归纳与注册

- `induce_skill(task, records, catalog)`：成功轨迹 → 模板；
  商品名替换为 `{product}`，纯数字且等于目标数量的输入值替换为 `{qty}`；
- `register_induced_skill(operation, template)` / `save_induced_skills(path)`
  / `load_induced_skills(path)`；
- `skill_for_subtask`：诱导注册表优先；**未注册的非 add 操作一律返回
  None**（能力缺口显式化，防止误路由到 add 技能）；
- 能力门控（AR012）经 `skill_for_subtask` 自动感知注册状态变化。

### FR6 评测

| 阶段 | 内容 | 判定 |
|------|------|------|
| P0 | 能力门控检查移除指令 | covered=False（缺口证据） |
| P1 | LLM 兜底真实执行移除 p3（seed p3×2） | 真实成功 + 轨迹记录 |
| P2 | 归纳 → 注册 → 持久化 JSON | 模板含 `{product}` |
| P3 | 同任务技能复跑（新会话） | 成功、0 policy 步 |
| P4 | 迁移：p4（v1）+ p3（v2 churn） | 技能路径成功 |
| P5 | 组合门禁：pytest 全量 + AR011 30 场景 | 不低于现状 |

## 4. 非功能

| 类型 | 要求 |
|------|------|
| 真实性 | 全链路真实浏览器/GPU 推理/服务端状态，无 mock |
| 端侧收益 | 复用后 0 LLM 调用、0 prompt tokens |
| 可复现 | 固定 seed=42、JSON 产物、固定适配器路径 |
| 安全 | URL 白名单、动作白名单、语义定位均沿用现状 |

## 5. 假设

- AR004 三个适配器产物在位（`outputs/ar004/*`）；
- LLM 兜底能完成「购物车页点击移除按钮」级别的任务（难度低于 AR015
  的数量改写基线）；
- 若 P1 失败，如实记录负结果并回退，不伪造归纳。

## 6. 术语

| 术语 | 定义 |
|------|------|
| 能力缺口 | 能力门控判定 `covered=False` 的任务类型 |
| 轨迹归纳 | 成功轨迹 → 参数化技能模板的自动泛化 |
| 模板实例化 | 模板占位符按目标任务商品/数量替换为可执行技能 |
