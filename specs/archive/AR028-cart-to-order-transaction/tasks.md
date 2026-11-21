# [AR028] 任务清单

| # | 任务 | 状态 |
|---|------|------|
| T1 | spec 三件套 + EX002 E7 依据 | passing |
| T2 | planner 复合 transform + checkout + promo | passing |
| T3 | runtime 券预检 + checkout + 订单失败回滚 | passing |
| T4 | tasks 谓词扩展 | passing |
| T5 | 真实测试 `tests/test_edge_cart_to_order.py`（6 项） | passing |
| T6 | 主评测 `scripts/ar028_eval.py`（baseline 0/3 → COT 3/3 + 预检/回滚） | passing |
| T7 | 真实 Edge GIF demo `scripts/ar028_demo_gif.py` | passing |
| T8 | 组合门禁（edge 181 + AR011 30/30 0 LLM） | passing |
| T9 | README v4.17 / REPRODUCTION §4.5.4 / BACKLOG / 封面 / 归档 | passing |
| T10 | Gitee 小包同步 + 全新 clone 验证 | passing |

## 执行记录

- T2/T3：`enable_compound=True` 时 transform 指令识别结算；券对照真实 promo 列表；
  预检用真实目录价与目标数量，门槛不足零动作。
- T3：CTC 后执行 checkout；订单验证失败先 cancel 再回滚购物车并复核。
- T5：`python -m pytest tests/test_edge_cart_to_order.py -q` → **6 passed**。
- T6：`outputs/ar028/eval/ar028_results.json`：
  baseline **0/3**、COT **3/3**、0 LLM / 0 tokens；
  double+checkout 订单 `{p3:2,p4:2}`；+满400减50 `total=1196/paid=1146`；
  预检失败 total=398 < 2000、steps=0、cart 原值；订单故障 cart 恢复、compensated=2；
  P0–P4 全 true。
- T7：GIF 5 帧、约 39.7KB，真实订单 `total=1196/paid=1146`。
- T8：edge **181 passed**；全量（排除 gpt2 网络）**255 passed / 3 skipped**；
  AR011 **30/30、0 LLM、0 tokens、79.28s**。
- T9/T10：README/REPRODUCTION/EX002/BACKLOG/归档/Gitee。

## devflow-review 自查

- Finding 1：券门槛不足却先改购物车。已改为预检零动作，测试通过。
- Finding 2：订单已生成但验证失败。已 cancel_order 后回滚，故障测试通过。
- Finding 3：baseline 可能误把结算算成功。已用 AR027 仅变换 + 用户期望验证器。
- Finding 4：GIF 不能伪造。已用真实 Edge 截图，订单金额来自服务端。
- Verdict：**PASS**。保留 AR028（baseline 0/3 → 3/3，0 LLM，真实回滚）。
