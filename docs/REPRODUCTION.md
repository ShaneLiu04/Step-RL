# Step-RL AR001 复现与大规模实验手册

本手册对应 **AR001–AR004：真实端侧 Verifier-Grounded Step-GRPO + 层级任务分解 + 语义动作**。所有实验均在真实 HTTP 商城 + 真实浏览器中执行，所有实验在真实 HTTP 商城与真实浏览器中执行。

---

## 1. 已验证的本地环境（端侧小模型）

| 项 | 值 |
|----|----|
| OS | Windows 11 |
| Python | 3.11.9 |
| GPU | Quadro RTX 5000 16GB（本机时钟被限制在 645 MHz，实测约 2.1 TFLOPS FP16） |
| PyTorch | 2.5.1+cu121 |
| Transformers | 5.15.1 |
| PEFT | 0.20.0 |
| 浏览器 | 系统 Edge 141（Playwright `channel="msedge"`） |
| 基座 | `Qwen/Qwen3-0.6B-Base`（596M，本地 HF 缓存） |

> Playwright 自带 Chromium 在企业代理下会 407。必须使用系统 Edge/Chrome：`BrowserEnv(channel="msedge")` 或设置 `STEP_RL_BROWSER_PATH`。

### 1.1 本地最小复现

```powershell
$env:PYTHONPATH = "D:\agentRL\Step-RL"
python -m pip install -r requirements.txt
python -m playwright install --help   # 不需要下载 Chromium

# 1) 真实浏览器采集专家轨迹（L1-L2）
python scripts/edge_pipeline.py --stage data --repeats 2

# 2) LoRA SFT
python scripts/edge_pipeline.py --stage sft --sft_epochs 1

# 3) 两组 RL 对照（本机建议先只跑 L3 数量任务，见 §3.3）
python scripts/edge_pipeline.py --stage rl --rl_epochs 2 --group_size 3 --max_steps 6 --ppo_epochs 1

# 4) AR001 四组合 + 路由评测
python scripts/ar001_eval_full.py
python scripts/ar001_eval_router.py

# 5) AR002 记忆/重规划对照（负结果，用于复现回退）
python scripts/ar002_eval.py

# 6) AR003 层级分解评测（稳定 DOM）
python scripts/ar003_eval.py

# 7) AR004 语义动作：数据 -> SFT -> 语义 RL -> 稳定/扰动评测
python scripts/ar004_train.py --stage all

# 8) AR005 跨布局零样本 + 重渲染压力
python scripts/ar005_eval.py

# 9) AR006 自然语言约束规划
python scripts/ar006_eval.py

# 10) AR007 环境漂移闭环重规划
python scripts/ar007_eval.py

# 11) AR008 观测压缩（效率层）
python scripts/ar008_eval.py
```

产物：

```
outputs/ar001/
  expert_sft.jsonl          # 真实专家轨迹（每步含 prompt/action/Φ）
  sft_adapter/              # LoRA SFT
  grpo_sparse/              # 稀疏奖励 GRPO
  grpo_vgdp/                # VGDP Step-GRPO
  eval/                     # 四组合与路由结果

outputs/ar002/eval/         # 记忆/重规划对照（回退）
outputs/ar003/eval/         # 层级分解（稳定 DOM）
outputs/ar004/              # 语义 SFT/RL + 稳定/扰动评测
outputs/ar005/              # 跨布局零样本 + churn
outputs/ar006/              # 约束规划 8 指令 × 3 条件
outputs/ar007/              # 动态漂移 + 闭环重规划
outputs/ar008/              # full vs pruned 观测
```

---

## 2. 实验设计

### 2.1 任务分层

| 等级 | 任务 | 谓词链 |
|------|------|--------|
| L1 | 搜索 | search_done |
| L2 | 加购 1 件 | search → product → cart |
| L3 | 指定数量 | search → product → cart(qty≥2) |
| L4 | 结算下单 | + cart_viewed → checkout_viewed → name_filled → address_filled → order_placed |
| L5 | 多商品结算 | 两次加购 + 完整结算 |

- **SFT 数据**：仅 L1–L2，商品 p1/p2。
- **RL 训练**：L3（qty，p1/p2）从起始页学习；L4/L5（结算）用相同专家前缀到达结算页。
- **留出评测**：L1–L5，商品 p3/p4，数量/组合均未在训练出现。

### 2.2 四个组合

| 组合 | SFT | RL | DOM 修复 | 验证器感知观测 |
|------|-----|----|----------|----------------|
| `sft` | ✓ | - | ✗ | ✓ |
| `sft_repair` | ✓ | - | ✓ | ✓ |
| `sparse_grpo_repair` | ✓ | 稀疏 | ✓ | ✓ |
| `vgdp_grpo_repair` | ✓ | VGDP | ✓ | ✓ |

> `sparse` 与 `vgdp` 使用完全相同的 SFT 权重、专家前缀、采样预算与评测协议；唯一差异是奖励函数。

### 2.3 奖励

```
VGDP:
r_t = 2.0·(Φ(s_{t+1}) − Φ(s_t))
    + 0.05·1[exec_ok] − 0.10·1[exec_fail]
    − 0.02
    − 0.10·1[loop]
    + (1.0 if terminal and success else −0.10 if terminal else 0)

Sparse:
r_t = −0.02 + (1.0 if terminal and success else 0)
```

`Φ` 只由服务端真实状态与 URL 计算，谓词见 `step_rl/edge/verifier.py`。

### 2.4 Step-GRPO

- 同一任务采样 `G` 条轨迹，按任务分组。
- 回报 `G_t = Σ γ^{k−t} r_k`，`γ=0.95`。
- 组内标准化得到步级优势 `A_t`。
- response token 继承所属步的 `A_t`。
- old log-prob 来自采样时 `log_softmax(scores)`，`temperature=1.0`，保证 ratio 一致。
- KL 使用关闭 LoRA adapter 的参考前向，k3 估计。

---

## 3. 本机实测结果（真实、可复跑）

### 3.1 数量控制对照（留出 p3/p4，qty=2，未参与训练）

| 组合 | 成功率 | 平均步数 | 平均进度 |
|------|--------|----------|----------|
| SFT | 0/2 | 8.0 | 0.67 |
| SFT + repair | 0/2 | 8.0 | 0.67 |
| Sparse-GRPO + repair | 0/2 | 8.0 | 0.67 |
| **VGDP-GRPO + repair** | **2/2** | **5.0** | **1.00** |

训练过程（2 epoch，G=3，2 个训练任务）：

| 指标 | Sparse | VGDP |
|------|--------|------|
| epoch 1 训练成功率 | 16.7% | 16.7% |
| epoch 2 训练成功率 | 33.3% | **66.7%** |
| epoch 2 平均 Φ | 0.722 | **0.833** |
| 平均步奖励 | −0.020 | **+0.322** |

### 3.2 全量留出矩阵（9 任务，真实 Edge，greedy）

| 组合 | 成功率 | 平均步数 | 平均进度 |
|------|--------|----------|----------|
| SFT | 44.4% | 5.78 | 0.76 |
| SFT + DOM 修复 | 55.6% | 5.78 | 0.79 |
| Sparse-GRPO + 修复 | 55.6% | 5.78 | 0.83 |
| VGDP-GRPO + 修复（单模型） | 66.7% | 5.33 | 0.85 |
| AR001 任务类型路由 | 77.8% | 5.11 | 0.90 |
| AR003 层级任务分解 | 100% | 5.89 | 1.00 |
| AR004 语义层级 | 100% | 6.33 | 1.00 |
| AR005 跨布局语义 | 100%（未见布局+churn） | 7.89 | 1.00 |
| AR006 约束规划 | 100%（8 条约束指令） | 10.50 | 1.00 |
| AR007 闭环重规划 | 2/2 动态 + 3/3 静态 | — | — |
| **AR008 观测压缩（最终效率层）** | **100%（5 任务）** | 8.00 | 1.00 |

逐任务报告：

- `outputs/ar001/eval/eval_report.md`（四组合）
- `outputs/ar001/eval/router.md`（AR001 路由）
- `outputs/ar003/eval/hierarchical.json`（AR003）
- `outputs/ar004/eval/*.json`（AR004 稳定 + 扰动）

AR001 路由规则（`step_rl/edge/router.py`）：

```
L1/L2（搜索/加购） -> SFT adapter
L3（数量控制）      -> VGDP adapter
L4/L5（结算/多商品）-> Sparse adapter
```

AR003 在此基础上按子目标再分解：

```
add p3      -> SFT
add p4×2    -> VGDP
checkout    -> Sparse
```

L4（数量 2 + 结算）与 L5（多商品）均从 0% 提升到 **100%**。

### 3.2.1 DOM 改版鲁棒性（AR004）

在观测快照之后随机化页面全部 DOM id：

| 接口 | L1–L2 成功率 | 原始非法动作 | 修复依赖 |
|------|--------------|--------------|----------|
| selector + 修复 | 0% | 100% | 100% |
| **语义 Set-of-Mark** | **100%** | **0** | **0** |

完整 9 任务（语义层级）：稳定 DOM 100% / ID 扰动 100%，平均步数 6.33，非法动作 0。

### 3.2.2 跨布局零样本（AR005）

第二套真实布局 ShopLite（不同 id/结构/顺序 + 干扰按钮）：

| 条件 | 接口 | 成功率 | 非法动作 |
|------|------|--------|----------|
| 稳定 v2 | selector | 100% | 2 |
| 稳定 v2 | 语义 | 100% | 0 |
| **v2 + 观测后 id 全随机化** | selector | **0%** | 99 |
| **v2 + 观测后 id 全随机化** | **语义** | **100%** | **0** |

### 3.2.3 约束任务规划（AR006）

| 条件 | 规划准确率 | 按用户期望成功率 |
|------|------------|------------------|
| 关键词基线 v1 | 0% | 12.5%（1/8 偶然） |
| 约束规划 v1 | 100% | 100% |
| **约束规划 v2 + ID churn** | **100%** | **100%** |

### 3.2.4 环境漂移闭环重规划（AR007）

| 场景 | 一次性基线 | 闭环监督器 |
|------|------------|------------|
| D1 库存骤降 -> 替代 | 失败 | **成功（p4→p2）** |
| D2 结算涨价 -> 预算替代 | 失败 | **成功（p3→p2）** |
| 静态回归 3 条 | — | **3/3，0 次重规划** |

### 3.2.5 观测压缩（AR008）

| 条件 | 成功率 | Prompt tokens | 决策 |
|------|--------|---------------|------|
| full | 100% | 10009 | 基线 |
| top-K 相关性裁剪 | 60% | 12570 | 回退 |
| 历史行压缩 | 0% | 15303 | 回退 |
| 仅移除干扰控件 | 100% | 9589（−4.2%） | 保留 |

### 3.2.6 组合回退记录（真实）

| 尝试 | 成功率 | 决策 |
|------|--------|------|
| AR001 路由 | 77.8% | 中间最优 |
| 技能记忆 prompt | 66.7% | 回退 |
| 验证器触发重规划 | 66.7% | 回退 |
| LoRA 权重融合 | 0% | 回退 |
| AR003 层级分解 | 100%（稳定 DOM） | 稳定 DOM 前最优 |
| AR004 语义层级 | 100%（同布局） | 前最优 |
| AR005 跨布局语义 | 100%（未见布局 + churn） | 前最优 |
| AR006 约束规划 | 100%（8 指令） | 前最优 |
| AR007 闭环重规划 | 2/2 动态 + 3/3 静态 | 前最优 |
| **AR008 观测压缩** | **100%，−4.2% tokens** | **最终效率层** |

### 3.3 本机算力说明

本机 GPU 时钟被锁定在 645 MHz，单次动作生成约 6–8 秒。为避免“用时间换结论”，本地采用：

- 数量任务对照：2 个训练任务 × G=3 × 2 epochs。
- 全量矩阵：9 个留出任务 × 4 组合 × 1 次 deterministic greedy。
- 不报告未实际运行的 7B/8B 数字。

---

## 4. 高速算力服务器复现（7B–8B）

### 4.1 硬件建议

| 配置 | 模型 | 训练方式 | 显存 |
|------|------|----------|------|
| 1×A100 40GB | Qwen2.5-7B-Instruct | LoRA SFT | ~20GB |
| 1×A100 40GB | Qwen2.5-7B + LoRA | VGDP Step-GRPO（policy+ref，bf16） | ~32–38GB |
| 4×A100 40GB | Qwen3-8B | LoRA + DeepSpeed ZeRO-2 | 可扩展 |
| 8×H100 80GB | Qwen3-8B | 全参数/长序列 | 推荐 |

端侧对照：`Qwen3-0.6B-Base` / `Qwen2.5-1.5B-Instruct`。

### 4.2 安装

```bash
git clone https://gitee.com/liu-xingyan04/step-rl.git
cd step-rl
pip install -r requirements.txt
# Linux 服务器可正常安装 Chromium
playwright install chromium
```

### 4.3 数据规模（服务器版建议）

| 数据 | 端侧 pilot | 服务器建议 |
|------|-----------|------------|
| 商品数 | 4 | 20–50 |
| SFT 任务 | 10（L1–L2） | 40（L1–L2） |
| SFT 轨迹 | 20 | 400–800 |
| RL 任务 | 5（L3–L5） | 30–60 |
| 每任务采样 G | 3 | 8 |
| RL epochs | 2 | 10–20 |
| 留出任务 | 9 | 60–100 |

采集扩展：在 `step_rl/edge/tasks.py` 增加 `TaskSpec`，在 `step_rl/edge/site.py` 增加商品；专家采集仍走真实浏览器。

### 4.4 服务器命令

```bash
export PYTHONPATH=$PWD
export STEP_RL_MODEL=Qwen/Qwen2.5-7B-Instruct   # 或本地路径
export STEP_RL_BROWSER_PATH=/usr/bin/chromium   # 可选

python scripts/edge_pipeline.py --stage data --repeats 5
python scripts/edge_pipeline.py --stage sft --sft_epochs 3 --model "$STEP_RL_MODEL"
python scripts/edge_pipeline.py --stage rl --rl_epochs 10 --group_size 8 \
  --max_steps 12 --ppo_epochs 2 --model "$STEP_RL_MODEL"
python scripts/ar001_eval_full.py

# 语义动作（最终方案）：数据 -> SFT -> 语义 RL -> 稳定/扰动评测
python scripts/ar004_train.py --stage all --model "$STEP_RL_MODEL"
```

> 当前 `run_sft` 的 `max_length` 默认 384（为端侧 16GB 调优）。7B 服务器建议在 Python 中直接调用：
>
> ```python
> from step_rl.edge.sft import run_sft
> run_sft("outputs/ar001/expert_sft.jsonl", "outputs/ar001/sft_adapter",
>         model_name="Qwen/Qwen2.5-7B-Instruct", epochs=3,
>         batch_size=4, grad_accum=4, max_length=1024)
> ```

### 4.5 大规模超参

| 参数 | 值 |
|------|----|
| LoRA r / alpha / dropout | 16 / 32 / 0.05，`all-linear` |
| SFT lr / epochs | 2e-4 / 3 |
| RL lr | 1e-5 |
| G（组大小） | 8 |
| γ / clip / KL β | 0.95 / 0.2 / 0.02 |
| ppo_epochs | 2 |
| max_steps | 12（L5 可 16） |
| 评测 | greedy，3 seeds，Wilson 95% CI |
| 统计 | 逐任务 paired bootstrap，报告均值±std |

### 4.6 预期资源与时间（参考）

| 阶段 | 1×A100 40GB |
|------|-------------|
| 数据采集（400 轨迹） | 1–2 h |
| SFT（400 轨迹，3 epochs） | 2–4 h |
| VGDP GRPO（30 任务 × G=8 × 10 epochs） | 18–30 h |
| 全量评测（100 任务 × 4 组合） | 2–4 h |

实际时间取决于浏览器交互延迟与模型推理速度。

---

## 5. 复现检查清单

- [ ] `outputs/ar001/run_manifest.json` 记录 GPU、torch、commit。
- [ ] 专家采集成功率 ≥ 95%（否则环境/验证器有问题）。
- [ ] SFT 后 L1–L2 留出任务成功。
- [ ] Sparse 与 VGDP 使用同一 `sft_adapter` 与同一 seed。
- [ ] 评测只读 `outputs/ar001/eval/*.json`，不使用任何硬编码表。
- [ ] 若 VGDP 未优于当前最优，保留上一最优并在报告中记录回退。

---

## 6. 已知限制

1. 本地商城是自建真实站点，不是公网电商；结论应表述为“真实 Web 交互结构上的验证”，不外推到所有网站。
2. 本地 GPU 被限频，pilot 规模小；7B/8B 结果需在服务器按 §4 重跑。
3. 专家前缀只用于 L4/L5 训练，评测无前缀；Sparse 与 VGDP 完全一致。
4. 目前动作空间为 6 类结构化动作，未覆盖拖拽、上传、验证码等。
5. 旧 `step_rl/training/*` 与历史 benchmark 保留兼容，不得用于论文/报告指标。
