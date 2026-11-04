# [AR005] 详细设计

| 字段 | 内容 |
|------|------|
| AR 编号 | AR005 |
| 关联 srs.md | ./srs.md |
| 日期 | 2026-11-04 |
| 状态 | Draft |

## 1. 动机

AR004 的语义动作已在同布局 id 变化下 100%。若只在同一布局验证，仍可能被质疑“语义名恰好等于旧文本”。AR005 用第二套真实布局检验：

- 组件实现不同；
- DOM 顺序不同；
- 额外干扰控件；
- 仍保持业务语义。

## 2. 第二套布局（ShopLite）

| 页面 | v2 关键元素 |
|------|-------------|
| 首页 | `input#kw-field aria-label=搜索商品`、`button#find-btn aria-label=搜索`、排序/筛选干扰按钮 |
| 搜索结果 | 同样的语义表单；商品链接 `a#card-pX aria-label=商品名`，顺序反转 |
| 商品页 | `input#count-field aria-label=数量`、`button#buy-btn aria-label=加入购物车`、收藏干扰 |
| 购物车 | `a#checkout-link-2 aria-label=去结算`、继续购物干扰 |
| 结算 | `input#buyer-field aria-label=收货人`、`input#addr-field aria-label=地址`、`button#submit-btn aria-label=提交订单`、返回干扰 |
| 订单 | 不同标题/结构，成功由服务端状态判定 |

服务端路由、会话、购物车、订单与 v1 完全一致，仅渲染不同。

## 3. 评测条件

| 条件 | 布局 | 接口 | churn |
|------|------|------|-------|
| A | v1 | semantic | 否 |
| B | v2 | semantic | 否 |
| C | v2 | selector | 否 |
| D | v2 | semantic | 是 |
| E | v2 | selector | 是 |

- 接口：
  - semantic：`eid` + `data-eid`，无 selector 修复；
  - selector：CSS selector + DOM 唯一匹配修复。
- 子目标预算：12（对两接口一致）。
- 层级分解与适配器路由沿用 AR003/AR004。

## 4. 结果解释

- 仅换布局：selector 仍可通过观测中的新 selector 工作 → 不足以区分接口。
- 布局 + 观测后 id churn：selector 的 selector 快照立即过期；语义 eid 仍有效。
- 因此正式结论使用 D/E 条件。

## 5. 风险

| 风险 | 缓解 |
|------|------|
| 语义名与 v1 完全一致，迁移过于容易 | 保留干扰按钮与不同顺序；后续 AR 可引入同义改写 |
| 步数预算导致假失败 | 统一提高到 12，并对失败逐任务诊断 |
| 评测偶发波动 | greedy、固定 seed、逐任务 JSON |

## 6. 文件

```
step_rl/edge/site.py          # layout v1/v2
scripts/ar005_eval.py         # 跨布局评测
tests/test_edge_layout_v2.py  # v2 路由/语义名/真实执行
```
