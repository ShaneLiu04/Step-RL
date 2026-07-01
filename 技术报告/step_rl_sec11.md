# 摘要

Step-RL v2.0 是一个面向 Web 自动化 Agent（智能体）的强化学习训练框架，专门针对大型语言模型（LLM, Large Language Model）驱动的 Agent 在长链路任务决策中的三大核心缺陷——**稀疏终局奖励**、**动作锚定幻觉（Grounding Hallucination）** 与 **早期错误累积**——提出系统级解决方案。本框架通过五大核心组件协同工作：基于 Evidential Learning（证据学习）的稠密进度估计器将稀疏成功/失败信号拆解为连续中间奖励；多属性级联匹配机制实现动作前置校验与自动修正；课程调度器（Curriculum Scheduler）按难度递增动态组织训练任务与奖励权重；确定性 MinHash 状态记忆模块检测循环并给予探索激励；PPO（Proximal Policy Optimization，近端策略优化）/GRPO（Group Relative Policy Optimization，组相对策略优化）策略优化器在 KL 约束下稳定更新策略。实验结果表明，Step-RL v2.0 将任务完成率从基线 **58% 提升至 86~91%**（相对提升 57%），动作锚定准确率从 **87.5% 提升至 95.8%**，平均完成步数从 **24.5 降至 11.5~13.2**（效率提升 46%），循环率从 32% 降至 4~6%。技术层面，确定性 MinHash 预计算排列实现跨进程一致的高效状态哈希；GRPO 省去价值模型（Value Model），在 4-bit 量化下仅需 **6~7 GB VRAM**，较 PPO 节省约 30% 显存，使单卡 RTX 4060 即可训练 7B 参数模型。

---

# 第11章 附录

## 11.1 术语表

- **LLM Agent**：基于大型语言模型的智能体，能够接收自然语言任务指令并生成可执行的动作序列以完成目标。
- **RLHF**：Reinforcement Learning from Human Feedback，基于人类反馈的强化学习，通过人类偏好数据训练奖励模型以优化策略。
- **PPO**：Proximal Policy Optimization，近端策略优化算法，通过裁剪目标函数限制策略更新幅度，保证训练稳定性。
- **GRPO**：Group Relative Policy Optimization，组相对策略优化，无需独立价值模型，以组内相对优势估计降低显存占用。
- **LoRA**：Low-Rank Adaptation，低秩适应，一种参数高效微调（PEFT, Parameter-Efficient Fine-Tuning）方法，仅训练低秩分解矩阵。
- **GAE**：Generalized Advantage Estimation，广义优势估计，通过参数 λ 平衡偏差与方差，估计状态-动作对的优势值。
- **Evidential Learning**：证据学习，通过神经网络预测 Dirichlet 分布参数实现不确定性量化，用于进度估计器的置信度建模。
- **MinHash**：最小哈希，一种用于快速估计集合相似度的概率算法，本系统采用预计算排列实现确定性哈希。
- **Grounding**：动作锚定，验证生成动作在真实环境中的可执行性，确保元素存在且可交互。
- **Curriculum Learning**：课程学习，按难度递增顺序组织训练任务，使模型从简单样本逐步过渡到复杂场景。
- **SPA**：Single Page Application，单页应用，页面内容通过 JavaScript 动态更新而不发生完整页面刷新。

## 11.2 配置文件示例

`config.yaml` 核心配置结构如下：

- **model**：`base_model`（主模型，如 Qwen/Qwen3-8B-Instruct）、`fallback_models`（降级备选）、`dtype`（计算精度 bf16/fp16/fp32）、`use_4bit`（4-bit 量化开关）。
- **lora**：`r`（秩，默认 64）、`lora_alpha`（缩放系数，默认 32）、`target_modules`（目标模块列表，覆盖 q/k/v/o_proj 及 MLP 层）、`dropout`（正则化率，默认 0.05）。
- **environment**：`browser`（浏览器类型，chromium）、`headless`（无头模式）、`viewport`（视口尺寸 1280×720）、`blocked_domains`（安全沙箱屏蔽域名列表）。
- **curriculum**：`total_epochs`（总轮数，默认 100）、`levels`（四级难度：单页/跨页/复杂表单/多目标）、`promotion_threshold`（晋升成功率阈值，0.90）。
- **reward**：`sparse`（稀疏成功/失败/步数惩罚）、`progress_estimator`（进度估计器配置，含不确定性方法 evidential）、`grounding`（动作校验奖励与修正惩罚）、`state_memory`（MinHash 循环检测与新颖性奖励）、`dynamic_weights`（三阶段动态权重调度：early/mid/late）。
- **training**：`algorithm`（算法选择，grpo/ppo）、`ppo`（PPO 超参：clip_range、kl_coef、gae_lambda、vf_coef 等）、`grpo`（GRPO 超参：group_size、clip_range、kl_coef 等）、`sft`（SFT Warmup 配置：学习率 2e-4、epoch 3、梯度累积 4）、`replay_buffer`（经验回放容量 10000、优先采样参数 alpha/beta）。
- **evaluation**：`num_episodes`（评测回合数，默认 100）、`metrics`（10 项指标列表）、`ablation_studies`（9 组消融配置）。
- **checkpoint**：`save_dir`（保存路径）、`keep_last_n`（保留最近 5 个）、`auto_resume`（自动恢复）。
- **demo**：`gradio_port`（7860）、`api_port`（8000）、`enable_human_feedback`（人工反馈开关）。
- **continual**：`enabled`（持续学习开关）、`bootstrap_threshold`（高置信度自标注阈值，0.95）、`retrain_interval_episodes`（重训练间隔，1000 回合）。

## 11.3 环境依赖清单

`requirements.txt` 核心依赖如下：

- **Python 3.10+**（推荐 3.10 或更高版本）。
- **核心深度学习**：`torch>=2.1.0`、`transformers>=4.40.0`、`accelerate>=0.28.0`、`datasets>=2.18.0`。
- **参数高效微调与 RL**：`peft>=0.10.0`（LoRA 实现）、`trl>=0.8.0`（RL 训练器）、`bitsandbytes>=0.43.0`（4-bit/8-bit 量化）。
- **Web 自动化**：`playwright>=1.43.0`（浏览器驱动）、`beautifulsoup4>=4.12.0`（HTML 解析）、`lxml>=5.1.0`（XML 处理）。
- **工具库**：`PyYAML>=6.0`、`numpy>=1.26.0`、`pandas>=2.2.0`、`scikit-learn>=1.4.0`、`pillow>=10.2.0`、`imagehash>=4.3.1`、`tqdm>=4.66.0`、`wandb>=0.16.0`、`matplotlib>=3.8.0`、`seaborn>=0.13.0`、`tabulate>=0.9.0`。
- **Demo 与 API**：`gradio>=4.25.0`（交互界面）、`fastapi>=0.110.0`、`uvicorn>=0.29.0`（服务部署）。
- **开发测试**：`pytest>=8.1.0`、`pytest-asyncio>=0.23.0`、`black>=24.0.0`、`isort>=5.13.0`、`flake8>=7.0.0`（代码风格与质量检查）。
- **可选分布式**：`deepspeed>=0.14.0`（多 GPU 分布式训练）。

## 11.4 部署 Checklist

1. **环境准备**：确认 Python 3.10+ 与 CUDA 11.8+（GPU 训练必需）；8GB+ VRAM 推荐 GRPO + 4-bit 模式。
2. **安装依赖**：执行 `pip install -r requirements.txt && playwright install chromium` 安装 Python 包与浏览器二进制文件。
3. **准备数据**：运行 `python scripts/prepare_mock_data.py` 生成 SFT 样本（126 条）与进度标注（41 个标签）。
4. **验证安装**：执行 `pytest tests/ -v`，预期 **52 项测试全部通过**；可选运行 `python scripts/end_to_end_test.py` 进行集成验证。
5. **SFT 训练**：`python -m step_rl.training.sft_warmup --config config.yaml --data_dir ./data/sft --output_dir ./outputs/sft_ecommerce --use_4bit`。
6. **进度估计器训练**：`python -m step_rl.reward.train_reward_model --config config.yaml --data_path ./data/progress/ecommerce_labels.json --output_dir ./checkpoints/progress_estimator --use_uncertainty yes`。
7. **GRPO/PPO 训练**：`python -m step_rl.training.grpo_trainer --config config.yaml --sft_adapter ./outputs/sft_ecommerce/sft_adapter --progress_model ./checkpoints/progress_estimator/best_model.pt --output_dir ./checkpoints/grpo`。
8. **评测**：`python -m step_rl.evaluation.benchmark --config config.yaml --mock`，输出包含成功率、锚定准确率、循环率等 10 项指标与消融对比。
9. **Demo 部署**：`python -m step_rl.demo.demo --config config.yaml --policy ./checkpoints/grpo/best_adapter`，访问 `http://localhost:7860` 启动 Gradio 交互界面。
10. **Docker 部署**：构建 `docker build -t step-rl:latest .`，通过 `docker-compose --profile demo up` 一键启动，或 `docker-compose --profile train up -d` 后台训练。
