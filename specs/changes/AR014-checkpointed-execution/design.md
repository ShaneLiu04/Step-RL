# [AR014] 详细设计

## 1. 精确验证

`TaskSpec.exact_quantity: bool = False`。

`verifier.cart_contains/order_placed`：

```python
satisfied = qty == required if exact else qty >= required
```

既有任务不变。

## 2. 会话保存

`BrowserEnv`：

```python
def save_state() -> dict:
    return await context.storage_state()

def start(storage_state=None):
    context = await browser.new_context(..., storage_state=storage_state)
```

服务端会话由 `sid` cookie 维持；新上下文加载 cookie 即恢复同一会话。

## 3. 崩溃恢复

```python
env1 = BrowserEnv(server)
await env1.start()
await env1.reset(task)
run add skills
state = await env1.save_state()
await env1.close()

env2 = BrowserEnv(server, storage_state=state)
await env2.start()
run checkout skill
verify exact
```

基线：env2 不加载 state，从头执行 add+checkout，购物车变 4 件。

## 4. 评测

3 个任务，真实浏览器关闭/重开；记录订单数量、成功、耗时。

## 5. 风险

| 风险 | 缓解 |
|------|------|
| storage_state 不含服务端状态 | 服务端按 cookie 会话，真实测试 |
| 精确验证误伤既有任务 | 默认 exact=False |
| 基线重复加购仍被 >= 判成功 | 本轮用 exact=True |
| 崩溃注入不真实 | 真正关闭 context/browser 后重开 |

## 6. 文件

```
step_rl/edge/tasks.py       # exact_quantity
step_rl/edge/verifier.py    # 精确比较
step_rl/edge/browser.py     # save_state / storage_state
scripts/ar014_checkpoint.py # 崩溃恢复
tests/test_edge_checkpoint.py
```
