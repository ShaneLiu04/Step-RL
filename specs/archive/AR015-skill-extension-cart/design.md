# [AR015] 详细设计

## 1. 服务器

- `/update/<pid>?qty=n`：`state.cart[pid]=n`，重定向 `/cart`；
- `/api/cart/set?pid=&qty=`：seed 初始化；
- v1/v2 购物车每项：
  - 数量输入 `aria-label="数量 {商品名}"`；
  - 更新按钮 `aria-label="更新数量 {商品名}"`。

## 2. TaskSpec

- `operation: str = "add"`；
- `seed_cart: Dict[str,int]`；
- `predicates: List[str]` 可选自定义谓词；
- `exact_quantity` 已有。

## 3. 验证器

- `cart_quantity_exact`：`cart.get(pid,0) == qty`。

## 4. 规划器

“把购物车中的无线充电器数量改为3”：

- 识别“改为/改成 N”；
- 目标商品来自 `_mentions`；
- 生成 operation=update、predicates=[cart_quantity_exact]、level=2、require_checkout=False。

## 5. 技能

```python
update_quantity_skill(pid, qty):
  goto /cart
  type role=spinbutton, name=商品名, value=qty
  click role=button, name="更新数量 {商品名}"
```

技能动作来自真实演示（在真实购物车页执行并记录）；扩展后 `skill_for_subtask` 支持 operation=update。

## 6. 评测

- 每个任务 seed 初始购物车；
- baseline：LLM hierarchy；
- skill：run_task（技能优先）；
- 精确谓词判定；记录订单/购物车、耗时。

## 7. 风险

| 风险 | 缓解 |
|------|------|
| LLM 也能完成 | 如实记录，保留效率收益 |
| 多商品数量输入歧义 | 用商品名限定 aria-label |
| seed 破坏其他任务 | 仅新任务设置 seed_cart |
| 技能失败 | 回退 LLM |
