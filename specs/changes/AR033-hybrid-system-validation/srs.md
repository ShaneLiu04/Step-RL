# [AR033] 混合系统级验证需求

## 目标
在现有 CPU/GPU 环境上闭环“确定性 adapter/verifier/transaction + 端侧 LLM 兜底 + 人工/证据层”，验证系统整体可达性。

## 范围
- `HybridSystem` 统一 local/remote 入口；
- CPU 30 场景 0 LLM；
- GPU 真实 Qwen 兜底未覆盖操作；
- Console 真实 local 会话；
- JD/淘宝/Amazon 只读状态；
- 证据 JSONL/截图/report。

## 不做
真实支付/提交订单、绕过风控、mock 成功。
