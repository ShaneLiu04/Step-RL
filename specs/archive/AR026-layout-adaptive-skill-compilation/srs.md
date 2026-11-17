# [AR026] 布局自适应技能编译需求设计说明书

| 字段 | 内容 |
|------|------|
| AR 编号 | AR026 |
| AR 主题 | layout-adaptive-skill-compilation |
| 关联 SR | BACKLOG B06（v3 布局零样本迁移） |
| 日期 | 2026-11-16 |
| 状态 | Draft |

## 1. 背景与目标

AR005 已证明语义动作可跨 v2 布局迁移，但 v2 仍保留 `input[type=number]`、
“搜索”按钮等与 v1 同构的控件。真实 Web 的异构性更强：搜索框可能是
`role=searchbox`，搜索按钮可能叫“查找”，数量控件可能是不带 `<input>` 的
加减步进器。固定技能模板会把这些差异当成失败（真实 v3 上
`Locator.fill: Element is not an <input>`）。

目标（B06）：新增真实 v3 商城布局，并实现 **LASC（Layout-Adaptive Skill
Compilation）**——技能步骤声明“能力”，运行时根据实时观测的控件清单编译为
等价动作。要求真实 v3 上 baseline 固定技能失败、LASC 成功，v1/v2 30 场景
零回退、0 LLM，且无 mock。

## 2. 范围

**In Scope：**
- `site.py`：v3 布局（无 id、`searchbox`/“查找”、`article` 卡片、数量步进器）；
- `browser.py`：观测包含 `[role=spinbutton]` 与 `aria-valuenow`；
- `skill_library.py`：`set_quantity` 语义微操作、角色/名称别名、`adaptive` 消融开关；
- `tests/test_edge_layout_v3_adaptive.py`、`scripts/ar026_eval.py`；
- README/REPRODUCTION/封面/BACKLOG/归档/Gitee。

**Out of Scope：** 新 LLM 训练、跨进程、v3 之外的新视觉/Canvas UI、mock 数据。

## 3. 功能需求

### FR1 真实 v3 布局
- 无任何 `id` 依赖；首页/搜索使用 `role=searchbox` + “查找”按钮；
- 商品/购物车数量使用 `spinbutton` 显示 + “增加/减少”按钮 + hidden qty；
- 结算、订单、优惠券保持真实服务端流程；promo 按钮 accessible name 不漂移。

### FR2 LASC 运行时编译
- `set_quantity`：若实时控件是 `<input>` → `type`；若是步进器 → 读取
  `aria-valuenow`，按差值点击“增加/减少”；目标=当前则无动作；
- `_find` 支持角色别名 `textbox↔searchbox`、名称别名 `搜索↔查找`；
- 控件缺失/目标非法/点击失败必须显式错误，不得静默降级。

### FR3 消融与兼容
- `adaptive=False` 保留旧固定步骤，用于真实 baseline；
- 默认 `adaptive=True`；v1/v2 的输入框分支必须与旧行为逐动作一致；
- 旧 AR021/AR023/AR025 审计与技能语义不变。

### FR4 验收
- v3 三任务：baseline 固定技能成功 <3/3；LASC 3/3、0 LLM、0 tokens；
- AR011 30 场景 30/30、0 LLM；
- edge 套件零新增失败。

## 4. 非功能需求

| 类型 | 要求 |
|------|------|
| 真实性 | 所有结果来自真实 Edge + LocalShopServer，禁止 mock |
| 可靠性 | 控件缺失显式失败；不得把失败伪装成功 |
| 性能 | LASC 不引入额外 LLM；动作数可审计 |
| 兼容 | v1/v2 30 场景零回退 |

## 5. 约束与假设

- v3 的步进器初始值由服务端页面给出 1 或购物车当前数量；
- 增加/减少按钮真实修改 hidden qty，再由表单提交；
- 每 session 独立服务端状态；
- 不改变既有动作白名单（click/type/goto/scroll/wait/finish）。

## 6. 术语

| 术语 | 定义 |
|------|------|
| LASC | 根据实时观测的控件能力编译技能动作 |
| 能力清单 | 当前页面可用的角色/名称/值/标签集合 |
| 步进器 | spinbutton 显示 + 增加/减少按钮 + hidden 输入 |
