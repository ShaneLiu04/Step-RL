# [AR030] 第二/第三站只读适配需求

| 字段 | 内容 |
|------|------|
| AR | AR030 |
| 范围 | 淘宝/天猫 + Amazon 只读 adapter |
| 状态 | 工程闭环；真实业务证据受限 |

## 目标
复用 AR029 `SiteAdapter` 框架，实现 Taobao/Tmall 与 Amazon 的只读搜索/详情/价格
读取；无账号时显式登录/风控阻塞，不绕过、不伪造。

## 功能需求
- `RemoteReadOnlyAdapter`：真实 Edge、登录态可选、限速/页面预算；
- Taobao/Amazon 站点 URL 与登录域只在 adapter；
- 结果记录 title/url/blocked/amount；空标题/登录/CAPTCHA 显式失败；
- 不执行点击/加购/下单/支付（read-only）。

## 验收
- 单测：URL、金额、登录/风控识别、只读动作拒绝；
- 真实只读尝试：成功或显式失败均可，但不得 mock；
- 不影响 AR029/local 回归。

## Out of Scope
账号登录、加购、下单、支付、风控绕过。
