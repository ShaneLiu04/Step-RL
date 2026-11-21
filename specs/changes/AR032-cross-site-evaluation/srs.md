# [AR032] 跨站评测需求

## 目标
跨站只读评测协议：Local 真实任务 + JD/Taobao/Amazon 只读状态；报告成功与显式 BLOCKED，不伪造成功率。

## 范围
- `scripts/ar032_cross_site.py`；
- 真实 Local 3 任务；远程 Adventure 只读；
- `outputs/ar032/eval/ar032_results.json`；
- MP4 从真实截图/GIF 帧生成。

## 验收
- Local 3/3；远程记录真实状态；
- 不填跨站成功率/CI（样本不足且账号受限）；
- 不 mock；MP4 来自真实帧。
