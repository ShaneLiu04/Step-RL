# Step-RL 安全编码审查（Python）

> 依据：secure-coding、华为安全编码规则（Python 分类）、python-coding-standards。
> 仓库为 Python-only，无 Java/前端源码、无 CodeHub MR/流水线报告：
> `java-coding-standards`、`huawei-java-standards`、`frontend-coding-guide` 不适用；
> `codecheck-fix`、`mr-pipeline-report` 无输入，未伪造执行。

## 1. 危险模式扫描

| 检查项 | 结果 |
|--------|------|
| `eval` / `exec` 执行外部输入 | 未发现（`model.eval()` 是 PyTorch 推理模式，不是执行字符串） |
| `shell=True` / `os.system` / `os.popen` | 未发现；subprocess 使用参数列表 |
| `pickle.load` / `yaml.load` | 未发现 |
| 硬编码密码/密钥/Token | 未发现 |
| 凭据入仓/日志 | storage_state 只在本地 `%LOCALAPPDATA%`；EvidenceWriter 脱敏 |
| 路径穿越 | 已修复：EvidenceWriter 对 site/run_id 做安全字符归一化 |
| 未认证 HTTP 接口 | Console 支持可选 `CONSOLE_TOKEN`（HTTP Header + WS query）；未设置时仅 127.0.0.1 本地开发 |

## 2. 修复

1. `EvidenceWriter` 增加 `_safe_component`，阻止 `../` 路径穿越；新增测试。
2. 脱敏扩展：`pt_key/pt_pin/thor/wskey`。
3. 安全门禁纳入 `scripts/code_quality.py`（compileall + ruff F/E9 + 测试）。
4. 无 mock；远程登录/验证码/支付仍由人工接管。

## 3. 已知安全边界/技术债

- Console 已有可选 token 认证；对外部署仍需完整登录/角色鉴权、CSRF/CORS 与审计。
- 部分清理路径使用宽 `except Exception`，用于资源关闭；后续可统一 `contextlib.suppress` + 结构化日志。
- 真实站点密码/扫码凭据不由本仓库接收；不实现自动支付/风控绕过。

## 4. 结论

- 本次范围内的 Python 安全红线未发现高危实现；
- 路径穿越与日志脱敏已加固；
- 生产化前需补齐 Console 认证与依赖扫描（bandit/pip-audit 未安装，未伪造结果）。
