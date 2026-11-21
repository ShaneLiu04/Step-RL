# [AR031] Agent Console 需求

## 目标
FastAPI Console：真实 local 运行、WebSocket 截图流、事件/验证器面板、暂停/恢复/审批/取消、审计。

## 范围
- `step_rl/console/app.py`；
- 真实 LocalShopServer 技能路径（0 LLM）；
- 审计 `outputs/ar031/sessions/<id>/events.jsonl`；
- 不包含 JD 登录接管/真实支付（后续）。

## 验收
- `/health`、非法站点/空任务拒绝；
- 真实 local 会话成功、截图非空、`finish` 事件；
- 全量回归不降。
