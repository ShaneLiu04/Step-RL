# [AR034] 端侧 LLM 自愈技能闭环需求

## 目标
LLM 兜底成功一次后，自动把真实轨迹归纳为技能并注册；下一次同类操作 0 LLM。baseline 无自愈应重复 LLM。

## 验收
- 真实 local remove：baseline 两次均 LLM；self-healing 第一次 LLM+注册，第二次 0 LLM。
- 只有验证器成功才注册；失败不注册。
- 不改变 add/search/checkout/update 既有路径；AR011 30/30 不回退。
- GIF 来自真实截图。
