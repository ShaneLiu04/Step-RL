# [AR008] 详细设计

## 1. 动机

E7：L5 每成功任务 3944 tokens；E8：生成 8.3s/步。端侧要降本，必须减少输入元素与无效动作，而不是换更大模型。

## 2. 评分函数

```python
score(el) = sum(weight(missing, el.name) for missing in current_missing)
          + 0.5 * nav_bonus(el)
          - 2.0 * decoy(el)
```

- 直接匹配 missing 的元素权重 3；
- 商品名/关键词匹配 2；
- 导航（购物车/首页/结算/订单）0.5；
- 干扰词（排序/筛选/收藏/返回/继续购物）−2；
- 保持原 DOM 顺序输出前 K=6。

## 3. 裁剪位置

`rollout_task` 每次 `env.observe()` 后：

```python
if observation_pruning:
    obs["elements"] = prune_elements(obs["elements"], task, missing)
```

不影响 `get_state`、验证器、控制器导航、动作执行。

## 4. 评测

| 条件 | 观测 | 适配器 |
|------|------|--------|
| full | 原 10 元素 | 语义多适配器 |
| pruned | 6 元素 | 同上 |

指标：成功率、步数、prompt/gen tokens、总耗时。

## 5. 回退

- 若 pruned 成功率 <100% 或 token 降低 <30%，保留 full，记录负结果。
- 若成功且 token 降低，AR008 成为最终优化层。

## 6. 风险

| 风险 | 缓解 |
|------|------|
| 裁掉必要元素 | 缺失谓词匹配元素必留；失败回退 |
| 训练分布偏移 | 不重训，报告限定为推理期特征选择 |
| 评分偏置 | 统一 K、固定 seed、逐任务 JSON |

## 7. 文件

```
step_rl/edge/observation.py   # prune_elements
step_rl/edge/rollout.py       # observation_pruning
step_rl/edge/hierarchical.py  # 透传
scripts/ar008_eval.py         # full vs pruned
tests/test_edge_observation.py
```
