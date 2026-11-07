# [AR012] 需求设计说明书

| 字段 | 内容 |
|------|------|
| AR 编号 | AR012 |
| AR 主题 | cpu-capability-runtime |
| 日期 | 2026-11-04 |
| 状态 | Draft |

## 1. 背景与目标

AR011 统一 Runtime 在 30 场景 0 LLM 调用，但仍默认加载模型。端侧部署应做到：

- 技能覆盖的任务 **不加载模型、不占 GPU**；
- 未覆盖任务显式标记 fallback，需要时再加载 LLM；
- 无 GPU 环境下，覆盖任务仍可并发执行。

AR012 增加能力门控与 CPU-first 运行时，并真实评测 30 场景在 model=None 下的表现。

## 2. 范围

**In：**
- `capability.py`：任务覆盖检测；
- `runtime.run_task(model=None)` 安全回退标记；
- CPU-only 30 场景评测；
- 4 路并发 vs 串行；
- 未覆盖指令的显式 unsupported；
- 单测、报告、README、复现文档。

**Out：**
- 新任务/新技能；
- 公网；
- 多机分布式。

## 3. 功能需求

### FR1 能力清单

- 根据 instruction/catalog 判断技能是否覆盖；
- 返回所需技能与是否覆盖。

### FR2 CPU-first

- 覆盖任务：不加载模型、不调用 GPU；
- 未覆盖任务：`fallback_required=True`，不静默失败。

### FR3 并发

- N 个独立会话并行执行技能任务；
- 记录串行/并行 wall time 与成功率。

### FR4 评测

- 30 场景，model=None；
- 成功率 100%，GPU 占用 0；
- 4 路并发成功率 100%，wall time 低于串行；
- 未覆盖指令明确 unsupported。

## 4. 非功能

| 类型 | 要求 |
|------|------|
| 训练成本 | 0 |
| 内存 | 不加载 0.6B 模型 |
| 可复现 | 固定 seed、JSON |
| 安全 | 真实 DOM/动作白名单 |

## 5. 假设

- 覆盖任务技能可完成；
- 并发受浏览器资源限制；
- 未覆盖任务需要 LLM，CPU-only 下不执行。

## 6. 术语

| 术语 | 定义 |
|------|------|
| 能力清单 | 指令到技能的覆盖映射 |
| CPU-first | 覆盖任务不加载模型 |
| fallback_required | 未覆盖任务需要 LLM |
