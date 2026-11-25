# Step-RL · FDE 工程化手册

> 用前置部署工程师（Forward Deployed Engineer）的视角审视 Step-RL：它不只是一个“跑出 30/30 的研究原型”，而是要能被带进客户现场、在受限网络和普通笔记本上 **装得上、跑得稳、证得明、管得住、算得清**。

---

## 1. FDE 岗位要求 → 本项目的落点

FDE 类岗位的核心要求可以归纳为七条。下表是每条要求在 Step-RL 中的对应交付物：

| FDE 要求 | 在客户现场意味着什么 | Step-RL 的交付物 |
|---|---|---|
| 端到端交付 | 从需求到可演示、可运维的产品，不是 notebook | `step-rl` CLI（doctor / studio / run / eval / privacy-scan）+ Step-RL Studio |
| 部署韧性 | 代理、无 GPU、无管理员权限、离线 wheel | `step-rl doctor` 环境体检；核心安装不依赖 torch；直接驱动系统 Edge |
| 正确性可证明 | 客户只认“订单真的下了”，不认模型说“我完成了” | 可执行验证器 Φ 读取服务端状态；`eval` 用 **独立的期望规格** 判分 |
| 安全与合规 | 不可逆动作要人批准、操作要可追溯、数据不外泄 | 下单前人工确认门禁；动作白名单与导航范围；`CONSOLE_TOKEN`；审计回放；隐私门禁 |
| 可观测与回归 | 每次改动都知道有没有退化 | smoke（6）/ unified（30）验证套件；`results.json + report.md`；CI 真实浏览器 smoke |
| 成本意识 | LLM 调用 = 钱 + 延迟 + 不确定性 | 编译技能 0 LLM 主路径；LLM 只做兜底，成功后归纳为技能摊销到 0 |
| 快速适配客户系统 | 新站点 / 改版不能重写 agent | 语义 Set-of-Mark 动作；按实时控件能力编译（AR026）；站点适配器（AR029/AR030） |

## 2. 深度优化的七个角度

### 2.1 产品化：一个安装，一个入口

**问题**：原仓库的入口分散在几十个 `scripts/*.py` 里，`pyproject.toml` 只有工具配置，安装路径依赖 `requirements.txt` 全量拉 torch/transformers。

**做法**：

- `pyproject.toml` 改为真实可安装包：核心依赖只有 `fastapi / uvicorn / pydantic / PyYAML / playwright`，训练与服务栈拆为 `[train] [serve] [track] [dev]` extras。
- 统一入口 `step-rl`（`python -m step_rl` 等价）：`doctor`、`studio`、`run`、`eval`、`scenarios`、`privacy-scan`。
- `step_rl/edge/rollout.py` 中的 `torch` 改为延迟导入，0 LLM 运行时在没有 torch 的机器上也能 import 和运行（有测试守护）。

### 2.2 部署韧性：先体检，再上线

`step-rl doctor` 是客户现场的第一条命令，逐项给出 ok / warn / fail 和修复提示：

```
python · core deps · playwright · browser · local shop · outputs dir · skill memory
studio auth · training stack · gpu · privacy gate · (--live) live browser
```

- `--live` 真实拉起浏览器打开本地商城，验证“浏览器能被驱动”这件最容易在现场出问题的事。
- `--strict` 把 warn 也当失败，适合放进客户的准入流水线；`--json` 给运维平台消费。
- 浏览器通道通过 `STEP_RL_BROWSER_CHANNEL` 切换（`msedge` / `chrome` / `chromium`），企业 Windows 机器无需下载 Chromium。

### 2.3 正确性：验证器是唯一事实来源

- 运行时、奖励、评测、审计 **共用同一个 Φ**（`compute_progress`），判定依据是服务端的购物车 / 订单 / 优惠状态。
- `step-rl eval` 的每个用例携带 **独立于运行时的期望规格**（例如 cart-to-order 期望 `p3×2, p4×2` 且服务端确认 `man400jian50` 已生效），避免“运行时自己说自己成功”。
- 统一套件复刻 AR011 的 30 个场景：v1 留出任务、8 条约束指令、动态与表单错误、v2 布局 + 每次观测随机化 ID。

### 2.4 安全治理：不可逆动作必须过人

| 风险 | 控制 |
|---|---|
| 误下单 / 误支付 | Studio 默认可开启“下单前人工确认”，`提交订单` 前挂起会话并弹出 iOS 风格 bottom sheet |
| 越权导航 | 导航范围限制在本地商城主机；动作白名单 `click · type · goto · scroll · wait · finish` |
| 未授权访问 | `CONSOLE_TOKEN`；`step-rl studio` 在没有令牌时 **拒绝绑定非回环地址** |
| 事后追责 | 每个会话写入 `outputs/studio/sessions/<id>/`：事件流、最终画面、结果，Studio「审计回放」可查 |
| 隐私泄露 | `step-rl privacy-scan`：通用检测（工作站路径、私钥、API Key、URL 内凭据）+ 本地私有词表（`.privacy-terms`，已 gitignore，命中时只报 `<redacted term>`） |

### 2.5 可观测与回归：每次提交都在真实浏览器里跑一遍

- CI：`ruff → privacy-scan → node --check → pytest (3.10/3.11/3.12) → step-rl doctor --live → step-rl eval --suite smoke`，评测报告作为 artifact 上传。
- 测试对环境做显式守护：缺 playwright、transformers 损坏（版本不匹配触发 `ImportError`）时跳过而不是收集失败。
- 评测输出同时给机器（`results.json / summary.json`）和人（`report.md`）。

### 2.6 成本：LLM 是兜底，不是驱动

- 覆盖任务全部走编译技能：统一套件 30/30，**0 LLM 调用、0 tokens**（AR011）。
- CPU 4 路并发 2.73× 加速（AR012），观测往返 −62.7%（AR025）。
- 未覆盖任务 → 端侧 LLM 兜底一次 → 验证器确认 → 参数化归纳为技能（AR019 / AR034）→ 之后 0 LLM 复用。成本曲线随使用时间下降，而不是线性增长。

### 2.7 适配：新站点是“编译”，不是“重写”

客户站点接入的推荐路径：

1. 用 `step-rl doctor --live` 确认浏览器与网络。
2. 实现只读站点适配器（参考 `step_rl/edge/adapters/`），先打通 search / product / cart 观测。
3. 为该站点写服务端（或页面权威区域）的验证谓词，让 Φ 可判定。
4. 把客户的 10–30 条典型任务写成 `Case`，形成该客户的回归套件。
5. 未覆盖任务交给 LLM 兜底，成功轨迹自动归纳为技能；在 Studio 打开人工确认后试运行。

## 3. 本轮升级落地清单

| 维度 | 变更 |
|---|---|
| 产品化 | 可安装包 + extras；`step-rl` CLI；版本号单一来源 `step_rl.__version__` |
| 前端 | Step-RL Studio：iOS × Codex 设计语言、深浅双色、实时画面、时间线、购物车/订单面板、人工确认 sheet、技能库、证据实验室、审计回放、系统页 |
| 品牌 | 新 logo（阶梯 = 层级步进，星标 = 验证通过的目标）、banner、架构图 |
| 部署 | `doctor`；torch 延迟导入；系统 Edge 默认；非回环地址强制令牌 |
| 评测 | `step_rl/ops/suites.py`：smoke 6 / unified 30，独立期望规格判分，并发运行，报告落盘 |
| 安全 | `step_rl/ops/privacy.py` 隐私门禁 + 测试；历史文档中的个人信息与内部标识清理 |
| 质量 | ruff 配置收敛到 pyproject（E/F/W/B/I）；测试环境守护；新增 ops/CLI 测试；CI 重写 |

## 4. 借鉴哪些开源项目，以及差异在哪里

| 项目 | 借鉴点 | Step-RL 的差异 |
|---|---|---|
| [browser-use](https://github.com/browser-use/browser-use) | 可交互元素索引化、LLM 驱动的浏览器循环 | LLM 只做兜底；主路径是编译技能 + 服务端验证 |
| [Stagehand](https://github.com/browserbase/stagehand) | `act / observe / extract` 原语、动作缓存以降低重复调用 | 缓存的不是单步动作而是 **带验证的参数化技能与事务** |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | 基于可访问性树的结构化观测 | 语义 `data-eid` + 验证器感知观测压缩 |
| [WebArena](https://github.com/web-arena-x/webarena) / [WebShop](https://github.com/princeton-nlp/WebShop) | 可复现的自托管站点 + 程序化判分 | Φ 同时进入训练奖励（VGDP / Step-GRPO）与运行时检查点 |
| [Voyager](https://github.com/MineDojo/Voyager) / Agent Workflow Memory | 技能库、从成功轨迹中归纳可复用流程 | 归纳出的技能必须经 Φ 验证，并按成功率统计与淘汰（AR021） |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | 事件流、会话轨迹回放 | Studio 审计回放 + WebSocket 实时画面 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Human-in-the-loop interrupt | 门禁绑定在“提交订单”这一不可逆动作上，审批结果写入审计 |
| [Temporal](https://github.com/temporalio/temporal) / Saga 模式 | 持久化执行、补偿事务 | 浏览器动作级的 CTC / COT 事务与失败回滚（AR014 / AR017 / AR028） |
| [TRL](https://github.com/huggingface/trl) GRPO | 组相对策略优化 | 以 Φ 的进度差分作为 **步级** 优势（Step-GRPO） |
| [inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai) / [promptfoo](https://github.com/promptfoo/promptfoo) | 评测即代码、报告产物 | 判分来自服务端状态而非 LLM-as-judge |
| [gitleaks](https://github.com/gitleaks/gitleaks) / detect-secrets | 密钥扫描 | 额外支持本地私有词表且命中只输出脱敏结果 |

## 5. 本项目的独特价值

1. **验证器贯穿全生命周期**：同一个 Φ 用于训练奖励、运行时重规划、评测判分和审计结论；“成功”在系统里只有一个定义。
2. **编译而非提示**：覆盖任务 0 LLM、0 tokens、确定性可复现；LLM 是能力边界之外的兜底，而不是每一步的驱动。
3. **会自愈的技能库**：失败 → 兜底 → 验证 → 归纳 → 统计淘汰，能力随使用增长、成本随使用下降。
4. **Web 动作的事务语义**：购物车 / 订单事务带预检与补偿，长链路操作有上界、可回滚、可审计。
5. **端侧优先**：普通笔记本 + 系统 Edge + CPU 即可运行完整闭环；训练栈是可选项。
6. **证据账本**：AR001–AR035 每次尝试都有规格、结果 JSON 和结论，负结果同样保留（28 次尝试 27 次进入最优组合，1 次归档）。

## 6. 下一步路线

| 优先级 | 事项 | 价值 |
|---|---|---|
| P0 | OpenTelemetry trace（会话 → 子目标 → 动作），对接客户已有 APM | 现场排障时间从小时级降到分钟级 |
| P0 | 审批策略文件（YAML）：按金额、商品、站点配置门禁 | 合规规则由客户自己维护 |
| P1 | 站点接入 SDK：录制一次人工操作 → 生成适配器骨架 + 验证谓词草稿 | 新客户接入从天级降到小时级 |
| P1 | Studio 多用户鉴权（OIDC）与会话隔离配额 | 从单人演示走向团队使用 |
| P2 | WebArena 购物子集的外部基准 | 与公开方法同场对比 |
| P2 | 离线安装包（wheelhouse + 浏览器检测） | 完全断网环境交付 |
