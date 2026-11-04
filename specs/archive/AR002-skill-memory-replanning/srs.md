# [AR002] 需求设计说明书

| 字段 | 内容 |
|------|------|
| AR 编号 | AR002 |
| AR 主题 | skill-memory-replanning |
| 关联 SR | 长链路 Web Agent 的状态-动作记忆与重规划 |
| 日期 | 2026-11-04 |
| 状态 | Draft |

## 1. 背景与目标

AR001 已建立真实环境、可执行验证器与 Step-GRPO，路由组合在 9 个留出任务上达到 **77.8%**。但真实评测暴露两个结构性失败：

- **L4 数量 + 结算**：加购数量正确后，模型在结算页重复旧动作，Φ 停滞。
- **L5 多商品结算**：模型丢失“第二个商品”的子目标，无法完成多段流程。

验证器已经知道“还缺什么”（`missing predicates`），但小模型无法把缺失信息转化为正确的下一步。  
本 AR 引入 **外部技能记忆（Skill Memory）** 与 **验证器触发重规划（Verifier-Triggered Replanning）**：

1. 从真实成功专家轨迹中提取“状态签名 → 动作模板”；
2. 推理时按当前页面/缺失谓词检索示范动作，写入 prompt；
3. 当 Φ 连续两步无提升或动作失败时，执行记忆动作进行真实重规划。

目标：在不新增训练成本的前提下，把 L4/L5 从 0% 提升，并使组合总成功率严格高于 AR001 的 77.8%；否则回退。

## 2. 需求范围

**In Scope：**

- 新增 `step_rl/edge/skill_memory.py`：记忆构建、检索、动作模板解析。
- 新增 `scripts/build_skill_memory.py`：从真实专家轨迹生成紧凑记忆 JSON。
- Prompt 增加 `参考动作`（仅 checkout 类任务，检索不到则不注入）。
- Rollout 增加验证器触发重规划（stagnation + failure）。
- 新增组合评测：`router`、`router + memory prompt`、`router + memory + replan`。
- README 重构：删除所有 mock 表述，突出动机、目标与架构。

**Out of Scope：**

- 新增 RL 训练（本轮只做推理期组合创新）。
- 新环境/新商品。
- 公网网站。

## 3. 功能需求

### FR1 技能记忆构建

**描述：** 从真实成功的专家轨迹提取紧凑记忆。

**输入：** `expert_all.jsonl`（真实浏览器执行，含每步 prompt/action/Φ/状态）。
**输出：** `step_rl/edge/skill_memory.json`，每条记录含：
`level`、`require_checkout`、`page_type`、`missing`、`action_template`、`delta_phi`、`target_pid`。

**验收：**
- Given 一条成功 L4 轨迹，When 构建，Then 记忆包含 checkout 页的 `name/address/place-order` 动作。
- 只允许训练任务（p1/p2）进入记忆；评测任务 p3/p4 不得泄漏。

### FR2 状态检索

**描述：** 按当前真实状态检索最相关动作。

**匹配键：** `require_checkout`、`page_type`（search/product/cart/checkout/order）、`missing` 集合、`target_pid` 是否已满足。
**排序：** 先按 missing 交集/并集 Jaccard，再按 `delta_phi` 降序。

**验收：**
- Given checkout 页且缺少 `name_filled`，Then 返回 `type #name` 模板。
- 无匹配时返回 `None`，不得随意建议。

### FR3 动作模板解析

**描述：** 将记忆动作适配到当前任务的商品/数量。

- `#product-pX` → 当前未满足的目标 pid；
- `type #q` → 当前目标商品关键词；
- `type #qty` → 剩余数量；
- 其他选择器保持。

**验收：**
- Given 评测任务 p4×2，When 解析 `#product-p1`，Then 变为 `#product-p4`。
- 解析结果必须在当前 DOM 中唯一命中，否则放弃。

### FR4 Prompt 注入

**描述：** 在策略 prompt 中加入一条参考动作。

**约束：** 仅 checkout 类任务注入；最多 1 条；不改变 SFT/RL 训练数据格式，仅在推理时使用。

**验收：**
- Given 检索成功，Then prompt 含 `参考动作: {...}`。
- Given 检索失败，Then prompt 与 AR001 完全一致。

### FR5 验证器触发重规划

**描述：** 当策略停滞时，用记忆动作真实执行一次。

**触发：**
- 连续 2 步 `Φ_after <= Φ_before`；或
- 当前动作执行失败且连续 2 步；
- 每 episode 最多触发 3 次。

**行为：** 执行记忆动作（真实浏览器），记录 `source=memory_replan`，随后把控制权交回模型。

**验收：**
- Given 结算页重复点击且 Φ 不变，Then 触发一次 `type #name` 或 `type #address`。
- 重规划不得绕过验证器或直接判定成功。

### FR6 组合评测与回退

**描述：** 在同一留出集上比较三个组合。

| 组合 | 说明 |
|------|------|
| `router` | AR001 最优 |
| `router_memory` | 路由 + 记忆 prompt |
| `router_replan` | 路由 + 记忆 prompt + 重规划 |

**验收：**
- 所有指标来自真实浏览器 episode JSON。
- 若 `router_memory`/`router_replan` 不高于 `router`，保留 `router` 并记录回退。
- 重点报告 L4/L5 逐任务结果。

## 4. 非功能需求

| 类型 | 要求 |
|------|------|
| 训练成本 | 0 新增训练 |
| 评测时间 | 单组合 9 任务 ≤ 10 分钟（本机限频 GPU） |
| 可复现 | 固定 seed；记忆 JSON 入仓；greedy 评测 |
| 安全 | 检索动作同样经过 DOM 唯一性校验与动作白名单 |
| 可维护 | 记忆构建、检索、重规划均有单测 |

## 5. 约束与假设

- 记忆只来自真实成功轨迹，且仅训练任务（p1/p2）。
- 检索与重规划不读取评测结果、不读取 gold answer。
- 端侧 GPU 限频，评测规模有限；结论按真实结果报告。

## 6. 术语

| 术语 | 定义 |
|------|------|
| Skill Memory | 从成功轨迹提取的状态→动作模板库 |
| Replanning | 验证器检测停滞后的真实动作干预 |
| 组合 | 路由适配器 + 记忆/重规划的叠加 |
| ΔΦ | 单步进度变化 |
