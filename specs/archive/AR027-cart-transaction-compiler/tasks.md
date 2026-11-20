# [AR027] 任务清单

| # | 任务 | 状态 |
|---|------|------|
| T1 | spec 三件套 + EX002 依据 | passing |
| T2 | TaskSpec / planner 支持 cart_transform | passing |
| T3 | runtime CTC + 逐项复核 + 补偿 | passing |
| T4 | 真实 HTTP 更新故障注入 | passing |
| T5 | 观测按 DOM 节点去重（多行 cart） | passing |
| T6 | 真实测试 `tests/test_edge_cart_transform.py`（6 项） | passing |
| T7 | 主评测 `scripts/ar027_eval.py`（baseline 0/3 → CTC 3/3 + rollback） | passing |
| T8 | 组合门禁（edge 175 + AR011 30/30 0 LLM） | passing |
| T9 | README v4.16 / REPRODUCTION / BACKLOG / 封面 / 归档 | passing |
| T10 | Gitee 小包同步 + 全新 clone 验证 | passing |

## 执行记录

- T2/T3：`cart_transform` 仅对“购物车/购物袋 + 所有/每件/都”生效；具体商品
  仍走 AR015 单商品路径；`double/set:N/add:N` 目标由真实 cart 解析。
- T3：每项 `update_quantity` 后用 `/api/state` 复核；失败按原数量补偿并复核。
- T4：`fault_update_once` + `fault_update_pid` 真实返回 500，用于补偿测试。
- T5：多行 cart 的 `input[name=qty]` 共享 CSS path；观测改为按 DOM 节点去重。
- T6：`python -m pytest tests/test_edge_cart_transform.py -q` → **6 passed**。
- T7：`outputs/ar027/eval/ar027_results.json`：
  baseline **0/3**（含旧 planner 误买 p1 的用户期望失败）；CTC **3/3**、
  0 LLM / 0 tokens；故障任务 success=false、`compensated=1`、cart 恢复原值；
  P0–P3 全部 true。
- T8：edge **175 passed**；全量（排除既有 gpt2 网络文件）**249 passed / 3 skipped**；
  AR011 **30/30、0 LLM、0 tokens、78.07s**。
- T9/T10：待文档与 Gitee 收尾。

## devflow-review 自查

- Finding 1：click 成功但服务端 500。已改为每步 `/api/state` 复核，故障测试通过。
- Finding 2：多行同 selector 丢元素。观测按 DOM 节点去重，6 项测试通过。
- Finding 3：具体商品指令误入 CTC。`_mentions` 非空即放弃，planner 测试通过。
- Finding 4：补偿可能再次失败。补偿后也复核，`compensated` 只计真实恢复项。
- Verdict：**PASS**。保留 AR027（baseline 0/3 → 3/3，0 LLM，真实回滚）。
