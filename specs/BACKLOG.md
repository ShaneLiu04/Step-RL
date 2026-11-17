# Step-RL 创新 Backlog（夜间自动化取材队列）

> 供每日 00:00–08:00 的 harnessX 自动化会话取用。每个条目按 AR 流程完整走
> srs → design → tasks → 实现 → 单测 → 真实评测 → 组合门禁 → README/归档
> → gitee 同步。**组合不优于现状即回退**（design §9.1 规则，负结果同样归档）。
> 取走一个条目后请在本文件标记 `claimed by AR0xx`；也可以按同样的质量标准
> 开辟新主题（新主题须先在本文件登记再动工）。

## 候选队列（按建议优先级）

| # | 主题 | 动机 | 验收要点 |
|---|------|------|----------|
| B01 | 多商品批量移除（remove 扩展） | AR019 只覆盖单商品移除；「清空 p3 和 p4」需要多目标模板实例化 | ≥2 商品任务 3/3，0 LLM；单商品不回退 |
| B03 | 诱导技能的冲突消解 | 同一操作多条诱导模板（不同来源轨迹）时如何选择 | 双模板同操作，评测选择更短/更成功者。注：「多候选并存 + 真实成功率选择 + 失败淘汰让位」核心机制已由 AR021 交付（见 specs/archive/AR021-skill-stats-priority/）；剩余增量 = 同成功率下的更短模板平局裁决 |
| B04 | 订单查询技能（order status）——claimed by AR022 | 用户侧高频操作：查订单状态/历史 | 真实订单页谓词 + 技能执行 3/3 |
| B05 | 优惠券/促销约束规划——claimed by AR023 | planner 目前只支持预算；满减券是新约束类型 | 规划准确率 100%（对照 naive 基线） |




## 已完成（从本队列毕业）

| 主题 | AR | 结论 |
|------|----|------|
| 失败驱动技能自动归纳 | AR019 | 见 specs/archive/AR019-skill-induction/ |
| 多商品批量移除（remove 扩展） | AR020 | 批量 3/3 + 单商品 3/3，0 LLM，约 10.5×；见 specs/archive/AR020-batch-remove/ |
| 技能库成功率统计与优先级 | AR021 | 0/1 失败留痕 → 淘汰让位，复用 4/4 0 LLM；30/30 不回退；见 specs/archive/AR021-skill-stats-priority/ |
| 订单查询技能（order status） | AR022 | 真实订单页谓词 + 3/3（0 LLM，含取消态迁移 + v2+churn）；LLM 兜底 1 步 186 tokens；见 specs/archive/AR022-order-status-query/ |
| 优惠券/促销约束规划 | AR023 | 8/8 规划（naive 0/8，4 组不可行指令诚实 None）+ 3/3 真实 Edge 执行 0 LLM（服务端 applied，省 50/150）；30/30 不回退；见 specs/archive/AR023-promo-constraint-planning/ |
| 并发会话隔离压测 | AR024 | 4 并发真实 Edge 4/4 零串扰（2.75×）；失败留痕 4/4；10×12 写者 0 损坏；串行零回退；见 specs/archive/AR024-concurrent-session-isolation/ |
| 观测缓存与增量 DOM diff | AR025 | 30/30、0 LLM；浏览器往返 1760→656（−62.7%）、observe 耗时 10.96s→4.06s（−63.0%）；cache probe 3/4 命中；见 specs/archive/AR025-observation-cache/ |
| v3 布局零样本迁移 | AR026 | v3 无 id/searchbox/查找/数量步进器；固定技能 baseline 1/3 → LASC 3/3（0 LLM）；AR011 30/30 零回退；见 specs/archive/AR026-layout-adaptive-skill-compilation/ |
