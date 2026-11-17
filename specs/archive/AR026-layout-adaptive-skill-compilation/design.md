# [AR026] 增量实现设计

## 1. 总体思路

在 AR025 的观测层之上增加一个 **运行时控件编译层**：

- 站点：v3 改变 DOM 结构与交互（searchbox/查找、无 id、步进器）；
- 技能：步骤只声明能力（数量、搜索、结算字段），执行时用最新观测选择
  真实控件并生成动作；
- 兼容：`adaptive=False` 保留旧固定模板作为真实 baseline；默认开启 LASC。

不改变动作白名单、验证器、成功判定、LLM 路径与持久化形状。

## 2. 模块改动

### 2.1 `site.py`（v3）

- `_page(layout="v3")`：ShopEdge 头部，无 id，链接保留 accessible name；
- `_render_v3_home/search`：`role=searchbox` + “查找”按钮 + `article` 卡片；
- `_render_v3_product/cart`：`span[role=spinbutton][aria-valuenow]` +
  “增加数量/减少数量”按钮 + hidden qty；inline JS 同步显示与 hidden 值；
- `_render_v3_checkout/order`：真实表单/订单页，无 id，字段名保持
  “收货人/地址/提交订单”；
- promo 卡 suffix 增加 v3，accessible name 不变。

### 2.2 `browser.py`

- 观测 selector 增加 `[role=spinbutton]`；
- `value` 字段回退到 `aria-valuenow`，使步进器当前值可被技能读取；
- AR025 单往返/缓存机制不变。

### 2.3 `skill_library.py`

- `ROLE_ALIASES` / `NAME_ALIASES`：`textbox↔searchbox`、`搜索↔查找`；
- `set_quantity` 微操作：
  - `input` 控件 → 旧 `type` 动作（v1/v2 逐动作不变）；
  - 步进器 → 读 `aria-valuenow`，按 `target-current` 点击增加/减少；
  - `current` 缺失时 fallback 到任意 spinbutton；仍缺失则显式错误；
- `add_item_skill` / `update_quantity_skill` 默认使用 `set_quantity`；
- `skill_for_subtask(task, adaptive=True)`、`run_skill_hierarchy(..., adaptive=True)`；
- `adaptive=False` 生成旧 `type` 步骤，作为真实 baseline 消融。

## 3. 关键决策

- **D1 能力导向而非选择器导向**：步骤名描述操作，`_find` 用别名匹配；
  真实控件差异由运行时消解。
- **D2 默认自适应、显式消融**：生产路径统一 LASC；baseline 必须走同一
  真实站点，只关闭自适应，避免伪造对照。
- **D3 步进器按差值点击**：不假设初始值；读 `aria-valuenow`，避免
  “目标 3 却多点一次”的 off-by-one。
- **D4 显式失败**：控件缺失/非法目标/执行失败返回错误，不 silent fallback。
- **D5 保持动作白名单**：不新增 select 等动作；步进器用 click 组合。

## 4. 测试设计

- HTTP：v3 无 id、searchbox/查找、spinbutton/增加数量、hidden qty；
- 真实 Edge：固定技能 v3 加购失败且 cart 不变；
- LASC v3：加购 p3×2、改量 2→3、真实结算 p4；
- 组合：edge 全套 + AR011 30 场景；
- 消融：`ar026_eval.py` baseline vs adaptive，同一 3 任务。

## 5. 风险与对策

| 风险 | 对策 |
|------|------|
| hidden qty 未随步进器更新 | inline JS 用 `this.form` 同步；真实测试覆盖 |
| 旧版数量输入无 aria-label | fallback 任意 spinbutton；debug 真实 v1 加购 |
| 步进器 off-by-one | 读 `aria-valuenow` 计算差值 |
| v1/v2 回归 | adaptive=False 旧路径 + AR011 30/30 门禁 |
| 角色别名误匹配 | 只对 textbox/searchbox 做别名；真实控件测试 |

## 6. 回滚

- 回退 AR026 提交：移除 v3 渲染与 `set_quantity`/别名，恢复固定技能；
- 产物保留 `outputs/ar026/`；AR025 观测缓存不受影响。

## 7. 组合回退规则

A = 当前最优 AR025（edge 164 passed + AR011 30/30 0 LLM）。
1. B = A + AR026；edge 套件不得新增失败。
2. B 的 AR011 必须 30/30、0 LLM；否则回退。
3. B 的 v3 三任务必须 3/3、0 LLM，且 baseline <3/3。
4. 全部满足 → 保留 B（README v4.15）；否则回退并归档负结果。
