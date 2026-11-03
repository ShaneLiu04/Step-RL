# [AR001] 需求设计说明书

| 字段 | 内容 |
|------|------|
| AR 编号 | AR001 |
| AR 主题 | edge-verifier-step-grpo |
| 关联 SR | 端侧 Web Agent 长链路 RL 真实化 |
| 日期 | 2026-11-03 |
| 状态 | Draft |

## 1. 背景与目标

现有仓库的训练入口、评测与 README 指标大量依赖 mock / 硬编码数据，无法支撑真实复现；同时 `finish` 无任务校验、课程任务未注册、KL 控制器返回值错误，导致“训练成功”是假信号。

本 AR 的目标是建立一条**端到端真实可运行**的端侧 Agent RL 流水线，并验证一个可量化的核心创新：

> **VGDP（Verifier-Grounded Dense Progress）+ Step-GRPO + DOM 接地修复**，在留出任务上显著优于 SFT 与稀疏奖励 GRPO。

## 2. 需求范围

**In Scope：**

- 新增真实本地商城（HTTP 服务 + 服务端会话/购物车/订单状态 + 可验证任务）。
- 新增真实浏览器环境（Playwright 驱动系统 Edge，真实 DOM、真实点击/输入）。
- 新增任务规格、可执行进度验证器、专家轨迹采集。
- 新增 LoRA SFT、真实 rollout、VGDP、步级 GRPO、动作接地修复。
- 新增真实评测矩阵（SFT / SFT+Repair / Sparse-GRPO / VGDP-GRPO）与自动报告。
- 修复阻断真实运行的既有缺陷：config→constructor 映射、任务注册、finish 任务校验、KL 更新返回值。
- 更新 README / 复现文档 / 实验配置 / 测试。

**Out of Scope：**

- 7B/8B 全参数训练与 vLLM 生产部署验证。
- 公网真实站点（受企业代理限制）。
- 旧 PPO/GRPO trainer 的彻底重写（仅修复阻断项）。
- 多模态训练。

## 3. 功能需求

### FR1 真实本地商城环境

**描述：** 提供可被真实浏览器访问的多页面商城，服务端维护会话状态。

**触发条件：** 启动 `LocalShopServer` 并通过 `http://127.0.0.1:<port>` 访问。

**期望行为：**
- 页面：首页、搜索结果、商品详情、购物车、结算、订单成功。
- 状态：搜索词、购物车条目/数量、表单、订单；通过 `/api/state` 返回 JSON。
- 每次会话隔离（cookie），支持 reset。

**异常处理：** 非法路由 404；非法数量 400；未登录/空购物车结算返回错误页。

**验收标准：**
- Given 新会话，When 访问首页并搜索，Then `/api/state.last_query` 等于搜索词且结果页包含匹配商品。
- Given 购物车为空，When 访问 `/checkout`，Then 不产生订单。
- Given 完整结算流程，When POST `/place-order`，Then `/api/state.order` 含正确商品与数量。

### FR2 可执行稠密进度验证器

**描述：** 从真实服务端状态与当前 URL 计算任务进度 Φ∈[0,1]。

**期望行为：** 每个任务定义有序谓词集合；Φ = 已满足谓词数 / 总谓词数；只依据真实状态，不使用模型输出。

**验收标准：**
- Given 任务 `checkout`，When 已加购但未结算，Then `0 < Φ < 1`。
- When 订单成功，Then `Φ = 1` 且 `success=True`。
- 同一状态重复计算 Φ 必须完全一致（确定性）。

### FR3 真实浏览器环境与动作执行

**描述：** 通过 Playwright 使用系统 Edge（`channel="msedge"`）执行动作。

**期望行为：**
- 观测包含 URL、标题、可交互元素（稳定选择器）、购物车摘要。
- 动作白名单：`click/type/goto/scroll/wait/finish`。
- `finish` 不直接判定成功，必须由验证器检查任务状态。
- 执行失败返回结构化错误，不伪造成功。

**验收标准：**
- Given 有效选择器，When click，Then 页面真实变化且 `ok=True`。
- Given 无效选择器，When click，Then `ok=False` 且 `error` 非空。
- Given 未完成任务，When finish，Then `success=False`。

### FR4 专家轨迹采集（真实交互）

**描述：** 脚本专家在真实浏览器中完成任务并记录逐步轨迹，用于 SFT。

**期望行为：** 轨迹包含 prompt、模型可见观测、JSON 动作、执行结果、Φ、终局成功；写入 JSONL。

**验收标准：**
- 采集 L1–L2 任务，成功率 ≥ 95%。
- 轨迹中每一步动作都在真实 DOM 上执行成功。
- 采集数据可被 SFT 直接加载，无 mock 环境。

### FR5 LoRA SFT

**描述：** 在 `Qwen3.5-0.8B-Base` 上做 response-only LoRA 监督微调。

**验收标准：**
- 仅对 response token 计算损失（prompt token 被 mask）。
- 训练 loss 下降并保存 adapter + tokenizer。
- 固定 seed 下重复训练结果可复现（允许浮点误差）。

### FR6 VGDP + 步级 GRPO

**描述：** 用真实 Φ 构造步级奖励，并按任务分组做 GRPO。

**期望行为：**
- 步奖励：`r_t = w_p·ΔΦ + w_valid·1[动作执行成功] + w_invalid·1[失败] - c_step + terminal·1[success]`。
- 同一任务采样 G 条轨迹，按组内 return-to-go 标准化得到步级优势。
- 每个 response token 继承其所属步的优势。
- old log-prob 与采样分布一致（temperature=1.0，`log_softmax(scores)`）。
- 含参考模型 KL（LoRA 关闭）与梯度裁剪。

**验收标准：**
- 训练日志记录真实 `policy_loss/kl/entropy/mean_reward`。
- 至少 3 个 epoch 无 NaN；checkpoint 可加载。
- 与 SFT 相同初始权重、相同评测协议。

### FR7 DOM 接地修复（推理期）

**描述：** 当模型给出的选择器不存在时，基于真实 DOM 做唯一匹配修复。

**期望行为：**
- 支持按 `id/name/placeholder/label/text/role` 匹配。
- 只有唯一匹配才重写选择器；否则返回失败，不猜测。
- 记录 `raw_invalid` 与 `repaired` 两个指标。

**验收标准：**
- Given 模型输出 `#wrong` 且页面有唯一按钮文本“搜索”，When 修复，Then 使用该按钮选择器并执行成功。
- Given 多个候选，When 修复，Then 放弃并返回失败。

### FR8 真实评测矩阵与报告

**描述：** 对 4 个组合在留出任务上执行真实评估并输出 JSON/Markdown。

**期望行为：**
- 组合：`sft`、`sft_repair`、`sparse_grpo_repair`、`vgdp_grpo_repair`。
- 指标：成功率、平均步数、平均 Φ、原始非法动作率、修复率、终局成功。
- 逐任务明细落盘；报告含硬件、模型、seed、命令、耗时。
- 若最优组合不是 VGDP，按回退规则保留上一最优并明确记录。

**验收标准：**
- 报告数字可由 `evaluate.py` 重跑复现。
- 所有指标来自真实浏览器执行，不读取硬编码表。

## 4. 非功能需求

| 类型 | 指标 | 要求 |
|------|------|------|
| 性能 | 单卡 16GB 可完成 SFT + 2 组 RL + 评测 | 总时长 ≤ 90 分钟 |
| 可靠性 | 训练 NaN / 崩溃 | 0 次（允许重试一次） |
| 可复现 | 固定 seed | 评测结果一致（确定性环境 + greedy） |
| 可维护 | 新增模块测试 | site/verifier/policy 单测覆盖核心分支 |
| 真实性 | mock/伪造指标 | 0 处进入实验结论 |

## 5. 约束与假设

**约束：**
- Windows + 企业代理，无法下载 Playwright Chromium；使用系统 Edge（已验证）。
- 模型离线缓存：`Qwen/Qwen3.5-0.8B-Base`（752M）。
- 训练使用 bf16 + LoRA，避免全参数显存开销。

**假设：**
- 任务成功可由服务端状态客观判定。
- 本地商城足以代表“长链路 Web 任务”的关键结构（搜索→选择→加购→结算）。
- 0.8B 模型经 SFT 后可稳定输出 JSON 动作格式。

## 6. 术语说明

| 术语 | 定义 |
|------|------|
| VGDP | Verifier-Grounded Dense Progress，可执行验证器给出的稠密进度 |
| Step-GRPO | 以步为信用分配单位、按任务分组的 GRPO |
| 接地修复 | 用真实 DOM 对无效选择器做唯一匹配修正 |
| Φ | 任务进度势函数，取值 [0,1] |
| 留出任务 | 训练中未出现的商品/数量/流程组合 |
