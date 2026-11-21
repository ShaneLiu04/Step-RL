# [AR030] 设计

- 新增 `adapters/remote.py` 通用只读 adapter；
- `taobao.py`/`amazon.py` 只配置 URL/登录域/商品域；
- 统一 `blocked_reason`：CAPTCHA/风控/登录页显式阻塞，空标题判失败；
- `execute` 直接拒绝；`catalog/promos` 为空；证据复用 AR029 EvidenceWriter。
