# [AR004] 需求设计说明书

| 字段 | 内容 |
|------|------|
| AR 编号 | AR004 |
| AR 主题 | semantic-som-robustness |
| 关联 SR | 面向动态 DOM 的语义动作接口 |
| 日期 | 2026-11-04 |
| 状态 | Draft |

## 1. 背景与目标

AR003 在稳定 DOM 上达到 100%，但动作仍绑定 CSS id/selector。真实网站一旦改版、SPA 重渲染或 id 随机化，策略输出立即失效。真实压力实验（观测后随机化全部 id）显示：现有 selector 接口在 L1–L2 上成功率为 **0%**，非法动作率 100%。

本 AR 将动作接口从“CSS selector”升级为 **Semantic Set-of-Mark（SoM-SAI）**：

- 观测为每个可交互元素分配临时语义编号 `e1/e2…`；
- 动作只引用编号，不依赖 id/name/class；
- 执行时通过 `data-eid` 在真实 DOM 中定位；
- 在“观测后 id 全随机化”的条件下仍可执行。

目标：在稳定 DOM 与 id 扰动两种条件下均达到 **100%**，且原始非法动作率为 **0**。

## 2. 需求范围

**In Scope：**

- `BrowserEnv` 语义观测：`eid / role / accessible_name`；
- 语义动作执行：`params.element = "eN"`；
- 真实 id 扰动压力模式（观测后随机化）；
- 语义专家轨迹、SFT、VGDP/Sparse 训练；
- 多适配器语义层级评测（稳定 + 扰动）；
- 单测：语义解析、prompt、真实浏览器执行；
- README/封面/复现文档更新。

**Out of Scope：**

- 公网站点；
- 视觉截图 Set-of-Mark；
- 新任务类型。

## 3. 功能需求

### FR1 语义观测

**描述：** 每个可交互元素输出 `eid`、`role`、`accessible_name`、`value`。

**验收：**
- Given 首页，Then 搜索框 name=搜索商品、搜索按钮 name=搜索。
- 同一步内 `eid` 唯一。

### FR2 语义动作

**描述：** `click/type` 支持 `params.element`，优先级高于 selector。

**验收：**
- Given 有效 eid，When click，Then 真实元素被点击。
- Given 无效 eid，Then 返回明确错误，不猜测。

### FR3 ID 扰动压力

**描述：** 观测快照后随机化页面所有 id，模真实 DOM 变化。

**验收：**
- Given 扰动开启，Then 观测中的 selector 立即过期；
- 语义 eid 仍可执行；
- 不能通过重新读取 DOM 偷偷修复 selector。

### FR4 语义训练

**描述：** 专家轨迹、SFT、VGDP/Sparse 全部使用语义动作。

**验收：**
- 语义轨迹中 click/type 只含 element；
- 训练后原始非法动作率为 0；
- L3 训练成功率 ≥80%。

### FR5 语义层级评测

**描述：** 用 AR003 层级分解 + 语义适配器评测 9 个留出任务。

**验收：**
- 稳定 DOM 成功率 100%；
- id 扰动成功率 100%；
- 非法动作/修复次数为 0。

### FR6 对照与回退

**描述：** 与 selector 接口在相同扰动下对照。

**验收：**
- 记录 selector 接口真实成功率；
- 若语义接口低于 AR003 稳定结果，回退并记录；
- 最终以“成功 + 鲁棒性 + 非法率”综合选择。

## 4. 非功能需求

| 类型 | 要求 |
|------|------|
| 训练成本 | 1 次 SFT + 2 次短 RL（端侧） |
| 评测时间 | 单条件 ≤10 分钟 |
| 可复现 | 固定 seed、greedy、JSON 产物 |
| 安全 | eid 只解析到当前观测元素，动作仍走白名单 |

## 5. 约束与假设

- `data-eid` 是临时标记，不改变业务逻辑；
- id 扰动只改 id，不改文本/role/可访问名；
- 语义编号每步重新生成，不跨页复用。

## 6. 术语

| 术语 | 定义 |
|------|------|
| SoM-SAI | Semantic Set-of-Mark Action Interface |
| eid | 单步观测内的元素编号 |
| ID churn | 观测后 id 被随机化的压力条件 |
| accessible_name | aria-label / placeholder / 文本 / name 的语义名 |
