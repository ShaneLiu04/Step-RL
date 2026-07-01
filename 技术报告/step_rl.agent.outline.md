# Step-RL v2.0 技术报告

## 摘要 (~300字)
### 核心定位
#### 面向Web自动化Agent的强化学习训练框架，解决长链路任务中的稀疏奖励、动作幻觉、错误累积三大瓶颈
### 关键技术成果
#### 通过稠密进度奖励+动作前置校验+课程动态调度+状态记忆循环检测+PPO/GRPO策略优化，任务完成率从58%提升至86%~91%
### 架构创新
#### 五位一体系统级方案：Progress Estimator(Evidential Learning不确定性量化)、Grounding Validator(多属性级联匹配)、Curriculum Scheduler(三阶段权重调度)、State Memory(MinHash+LRU)、GRPO/PPO Trainer(统一的last-token log-prob)

## 1. 引言 (~800字, 1张图)
### 1.1 背景与动机
#### 1.1.1 LLM Agent在长链路Web任务中面临稀疏终局奖励、动作锚定幻觉、早期错误累积三大核心难题
#### 1.1.2 传统SFT方案仅依赖单步Prompt+稀疏成功/失败信号，导致信用分配困难、策略收敛极慢
### 1.2 项目目标
#### 1.2.1 构建端到端强化学习训练框架，将任务完成率提升至≥86%，动作锚定准确率≥95.8%
#### 1.2.2 支持8GB VRAM友好训练，提供Docker容器化部署与Gradio交互Demo
### 1.3 报告范围与受众
#### 1.3.1 主要面向技术决策者、架构师、团队Leader；覆盖系统架构、核心模块、实现细节、DevOps、安全与性能
#### 1.3.2 报告范围涵盖v2.0全部源码、配置、测试与部署文档；不包含v1.0历史回顾与外部竞品对比

## 2. 系统概述与业务上下文 (~1500字, 2张图)
### 2.1 业务痛点与解决思路
#### 2.1.1 稀疏延迟奖励：仅终局有反馈，中间步骤无信号，信用分配困难——引入Progress Estimator稠密进度奖励
#### 2.1.2 动作锚定幻觉：LLM生成动作指向不存在元素——引入Grounding Validator前置校验与自动修正
#### 2.1.3 错误滚雪球：早期小错在长链路中被指数放大——引入课程动态调度与循环检测惩罚
### 2.2 核心功能边界
#### 2.2.1 功能范围：Web自动化任务(电商搜索/加购/下单、表单填写、跨页导航)，支持click/type/scroll/goto/wait/finish六种动作
#### 2.2.2 非功能需求量化：任务完成率≥86%、动作锚定准确率≥95.8%、平均完成步数≤13.2步、循环检测率≤6%
### 2.3 上下游系统依赖
#### 2.3.1 上游：Hugging Face模型仓库(Qwen3-8B-Instruct)、Playwright浏览器环境、用户任务指令输入
#### 2.3.2 下游：Gradio Demo服务(端口7860)、FastAPI推理服务(端口8000)、训练输出(checkpoint/adapter/benchmark)

## 3. 整体架构设计 (~2000字, 3张图, 2个对比表)
### 3.1 设计原则
#### 3.1.1 模块化解耦：环境、奖励、策略、训练、评测独立模块，支持独立测试与替换
#### 3.1.2 可扩展性：YAML配置驱动、插件式奖励组件、课程级别可自定义
#### 3.1.3 安全优先：沙箱域名过滤、选择器输入转义、非root容器运行、weights_only模型加载
### 3.2 分层架构
#### 3.2.1 接入层：PlaywrightWebEnv(浏览器沙箱)+GroundingValidator(动作校验)+Locator(共享定位模块)
#### 3.2.2 业务层：Agent策略网络(Qwen3-8B+LoRA Adapter)、Progress Estimator(稠密奖励)、State Memory(循环检测)
#### 3.2.3 控制层：Curriculum Scheduler(课程调度)、Continual Learning(持续学习)、Reward Summation(动态奖励合成)
#### 3.2.4 训练层：BaseTrainer(抽象基类)→PPOTrainer/GRPOTrainer(策略优化)
#### 3.2.5 数据层：训练轨迹(JSON/JSONL)、进度标注(JSON)、模型权重(Safetensors/PT)、评测结果(CSV/PNG)
### 3.3 关键技术选型及对比
#### 3.3.1 基座模型：Qwen3-8B-Instruct vs Qwen2.5-7B/14B降级兼容；选型理由：中文支持优秀、指令遵循能力强、开源可商用
#### 3.3.2 浏览器自动化：Playwright vs Selenium；选型理由：原生异步支持、Chromium无头模式稳定、JS注入能力强
#### 3.3.3 RL算法：PPO(GAE+ValueHead) vs GRPO(组相对优势)；GRPO节省30%VRAM，适合8GB GPU
#### 3.3.4 微调框架：PEFT/LoRA vs 全参数微调；LoRA r=64仅训练0.1%参数，保持基座能力
### 3.4 架构演进(v1.0→v2.0)
#### 3.4.1 v1.0痛点：固定权重奖励、仅PPO、无循环检测、无经验回放、无课程调度
#### 3.4.2 v2.0重构：BaseTrainer提取公共逻辑消除80%重复、Locator共享消除Env/Validator定位重复、动态权重调度+课程学习+状态记忆+GRPO支持

## 4. 核心模块与接口设计 (~2500字, 3张图, 3个代码片段, 1张接口表)
### 4.1 PlaywrightWebEnv环境模块
#### 4.1.1 类设计：Observation/Action/StepResult dataclass + PlaywrightWebEnv生命周期管理(start/stop/reset/execute_action)
#### 4.1.2 观测提取：JS DOM Extractor获取元素tag/role/text/id/coords，Fallback到BeautifulSoup；Token控制在2048以内
#### 4.1.3 安全沙箱：validate_url精确域名匹配(非子串)、blocked_domains拦截localhost/127.0.0.1/file://
### 4.2 GroundingValidator动作校验模块
#### 4.2.1 校验流程：元素存在性→可交互性(visible+enabled+bounding_box)→角色合法性→自动修正建议
#### 4.2.2 多属性级联匹配：element_id > element_text+tag > xpath > css_selector > coordinate_fallback(共享locator.py)
#### 4.2.3 智能修正：Jaccard bigram相似度匹配候选元素，相似度≥0.85自动修正，否则降级为wait
#### 4.2.4 错误码设计：valid(0.1)、corrected(-0.05)、failed(-0.2)、not_visible/not_enabled/not_editable/invalid_url
### 4.3 ProgressEstimator进度奖励模块
#### 4.3.1 架构：冻结Qwen3-8B Encoder + MLP回归头(3层512维) + Evidential不确定性头(gamma/nu/alpha/beta)
#### 4.3.2 训练损失：MSE + Margin Ranking Loss + Monotonicity Hinge Loss + Evidential NLL，权重{1.0, 0.5, 0.3, 0.5}
#### 4.3.3 设备同步：_sync_device()自动检测encoder设备并将自定义heads同步到同一设备，解决device_map="auto"分散问题
#### 4.3.4 接口契约：输入(input_ids, attention_mask, step_count)→输出ProgressOutput(progress∈[0,1], uncertainty∈[0,1])
### 4.4 StateMemory状态记忆模块
#### 4.4.1 确定性MinHash：预计算排列+短文本fallback，使用hashlib.md5替代随机数，保证跨进程一致
#### 4.4.2 循环检测：滑动窗口(默认3步)检测状态重复，loop_penalty_base=-0.1按loop_counter累加惩罚
#### 4.4.3 新奇性奖励：首次访问状态给予novelty_bonus，随visited_states/max_states衰减
#### 4.4.4 LRU淘汰：OrderedDict+popitem(last=False)实现真正的LRU，替代v1.0的set无序结构
### 4.5 CurriculumScheduler课程调度模块
#### 4.5.1 难度分级：4级课程(单页2-3步/跨页4-7步/复杂表单8-15步/多目标15-30步)
#### 4.5.2 动态采样：early阶段50%L1+40%L2+10%L3，late阶段10%L1+10%L2+40%L3+40%L4，线性插值
#### 4.5.3 权重调度：early grounding主导(β=2.0)、mid progress主导(α=2.0)、late progress精细化(α=2.5, ε=0.2)
#### 4.5.4 晋升机制：当前级别成功率≥90%且样本≥10条自动晋升，滑动窗口20条

## 5. 数据模型与存储方案 (~1200字, 2张图, 1张数据表)
### 5.1 训练数据模型
#### 5.1.1 轨迹格式：JSON对象{task_goal, difficulty_level, steps[{observation, thought, action, params}]}
#### 5.1.2 进度标注格式：JSON对象{text(观测+目标), progress∈[0,1], step_count, trajectory_id, outcome}
#### 5.1.3 对比排序对：从同任务成功/失败轨迹构建(s_i, s_j)对，target=1表示s_i进度更高
### 5.2 模型存储
#### 5.2.1 LoRA Adapter：PEFT格式保存至{output_dir}/sft_adapter，含adapter_config.json+adapter_model.safetensors
#### 5.2.2 基座模型：Hugging Face Hub下载，本地缓存于./models，支持Qwen3-8B/Qwen2.5-7B/14B
#### 5.2.3 Checkpoint：torch.save保存epoch/policy_state_dict/optimizer/algorithm，支持断点续训
### 5.3 缓存与索引
#### 5.3.1 状态记忆缓存：内存中OrderedDict(max_states=500)，无需持久化，每episode reset
#### 5.3.2 经验回放：deque(maxlen=10000)存储Trajectory对象，均匀采样(优先回放PER尚未实现)
### 5.4 数据生命周期
#### 5.4.1 训练数据：SFT数据(data/sft/)→进度标注(data/progress/)→高置信度轨迹自动标注自举循环
#### 5.4.2 模型版本：保留最近5个checkpoint(keep_last_n=5)，自动resume支持
#### 5.4.3 日志输出：训练日志→logs/，评测结果→outputs/benchmark/，消融表格→CSV+Markdown

## 6. 关键技术实现深度剖析 (~2500字, 3个代码片段, 2张对比表)
### 6.1 高并发Web环境交互(异步架构)
#### 6.1.1 Playwright async API：start/stop/reset/get_observation/execute_action全异步，避免阻塞训练循环
#### 6.1.2 JS DOM提取：page.evaluate注入自定义脚本提取元素属性，比accessibility.snapshot()更可控且兼容性更好
#### 6.1.3 资源拦截：route.abort()拦截png/jpg/css/woff等静态资源，加速页面加载
### 6.2 分布式奖励塑形与不确定性量化
#### 6.2.1 Evidential Learning：预测Dirichlet参数(gamma,nu,alpha,beta)，uncertainty=1/nu，替代传统MC Dropout
#### 6.2.2 不确定性衰减：r_progress_weighted = r_progress * (1.0 - uncertainty)，高不确定性降低奖励权重防噪声
#### 6.2.3 单调性约束：Hinge Loss on negative differences，强制同轨迹progress(t+1)≥progress(t)
### 6.3 PPO/GRPO策略优化核心实现
#### 6.3.1 last-token log-prob代理：rollout和update阶段均计算response最后一个实际生成token的log-prob，避免argmax错误
#### 6.3.2 _get_update_log_probs()：拼接prompt+response，取last valid token的logits，用Categorical分布计算log_prob
#### 6.3.3 GAE优势估计(PPO)：γ=0.99, λ=0.95，标准前向递推+归一化；GRPO组内归一化：A_i=(R_i-mean)/std
#### 6.3.4 KL自适应：kl_adaptive=True时，kl>target*2则kl_coef*=1.5，kl<target/2则kl_coef/=1.5，clamp到[0.01,1.0]
### 6.4 算法复杂度分析
#### 6.4.1 MinHash复杂度：O(n*k) where n=words, k=64 permutations；空间O(max_states)；短文本fallback到MD5
#### 6.4.2 GRPO vs PPO显存对比：GRPO 2模型(Policy+Ref)≈16GB FP16/6-7GB 4-bit；PPO 3模型≈24GB FP16/10-12GB 4-bit
#### 6.4.3 推理延迟：单步≈prompt编码(4096 tokens)+生成(256 tokens)+Grounding校验+Progress估计，A100/L40S约1-2s

## 7. 基础设施与DevOps (~1500字, 2张图, 2张配置表)
### 7.1 容器化部署
#### 7.1.1 Dockerfile多阶段构建：Stage1(builder)安装依赖+Playwright浏览器，Stage2(runtime)非root用户运行
#### 7.1.2 基础镜像：mcr.microsoft.com/playwright/python:v1.43.0-jammy，自带Chromium+依赖
#### 7.1.3 非root安全：USER appuser，groupadd/useradd创建独立用户，防止容器逃逸
### 7.2 Docker Compose编排
#### 7.2.1 四服务配置：demo(端口7860)、train(GPU)、benchmark、full-demo，通过profiles隔离
#### 7.2.2 数据卷映射：./data→/app/data, ./outputs→/app/outputs, ./models→/app/models, ./config.yaml→/app/config.yaml
### 7.3 CI/CD流水线
#### 7.3.1 GitHub Actions CI：Python 3.10/3.11矩阵测试、pytest覆盖率、black/isort/flake8/mypy/bandit安全扫描
#### 7.3.2 Docker构建流水线：buildx多阶段构建、缓存优化、tagged推送(v*语义化版本)
### 7.4 监控与日志
#### 7.4.1 日志体系：统一logging_utils.get_logger()，结构化输出，支持wandb集成(配置中report_to="none"默认关闭)
#### 7.4.2 健康检查：Docker HEALTHCHECK每30s执行python -c "import step_rl"
#### 7.4.3 资源监控：训练时检测GPU显存，<32GB自动启用更激进gradient checkpointing+半精度+提示切换GRPO

## 8. 安全与合规 (~1200字, 1张攻击面表, 1张代码引用表)
### 8.1 认证授权
#### 8.1.1 无外部认证：本地训练框架，无用户体系；Demo通过Gradio暴露，建议在内部网络运行
#### 8.1.2 模型加载安全：全量torch.load(..., weights_only=True)，防止pickle反序列化攻击
### 8.2 输入安全
#### 8.2.1 URL过滤：validate_url()使用urlparse精确提取hostname，精确匹配+子域名匹配，排除子串绕过
#### 8.2.2 选择器转义：escape_css_string处理反斜杠/引号/换行/空字节；escape_xpath_string使用concat()分片
#### 8.2.3 参数注入修复：str_to_bool自定义解析器处理yes/no/true/false/1/0，避免argparse布尔注入
### 8.3 数据安全
#### 8.3.1 训练数据脱敏：轨迹数据不包含真实用户凭证，电商场景使用模拟站/沙箱账号
#### 8.3.2 容器隔离：Docker沙箱运行，禁止在真实支付/订单环境训练
### 8.4 审计与合规
#### 8.4.1 动作可解释性：策略输出必须包含thought字段，便于审计调试，禁止黑盒动作
#### 8.4.2 安全扫描：bandit静态安全扫描，CI中自动生成bandit-report.json

## 9. 性能与容量评估 (~1200字, 2张图, 2张对比表)
### 9.1 压测结果摘要
#### 9.1.1 消融实验：sft_baseline 58%→sparse_ppo 68%→+progress_only 74%→+grounding_only 71%→full_v2(PPO) 86%→grpo 91%
#### 9.1.2 核心指标：完成率86~91%、动作锚定准确率95.8%、平均步数11.5~13.2、循环率4~6%
### 9.2 资源消耗基线
#### 9.2.1 VRAM占用：PPO FP16≈24GB/4-bit≈10-12GB；GRPO FP16≈16GB/4-bit≈6-7GB；单卡RTX 4060 8GB可行
#### 9.2.2 CPU/内存：推理阶段CPU占用低，训练阶段GPU为主；内存需求取决于batch_size和seq_length
### 9.3 容量规划
#### 9.3.1 当前容量：单卡训练，batch_size=1-8，gradient_accumulation=4，max_seq_length=2048-4096
#### 9.3.2 未来6-12个月扩展：DeepSpeed ZeRO-2/3多卡分布式(配置已列出但未集成)、FP8量化、模型蒸馏至1B

## 10. 已知问题与技术债务 (~800字, 1张债务表, 1张Roadmap)
### 10.1 当前技术债务
#### 10.1.1 [Critical]自定义RL为简化实现：last-token log-prob代理，生产环境建议迁移至trl.PPOTrainer/GRPOTrainer
#### 10.1.2 [High]Label Masking近似：SFT使用prompt长度近似masking，BPE边界可能有微小偏差
#### 10.1.3 [High]Replay Buffer均匀采样：配置化的PER(优先经验回放)尚未实现
#### 10.1.4 [High]多GPU支持：DeepSpeed配置已列出但未集成，当前仅单卡
### 10.2 Q1/Q2优化Roadmap
#### 10.2.1 Q1(v2.1)：集成trl官方Trainer、实现PER、模型蒸馏至1B级、多模态融合(截图视觉编码)
#### 10.2.2 Q2(v2.2)：DeepSpeed/FSDP多卡分布式、Demo人类反馈回传持续学习、支持Llama/Mistral、离线RL训练

## 11. 附录 (~600字)
### 11.1 术语表
#### 11.1.1 关键术语：LLM Agent、RLHF、PPO、GRPO、LoRA、GAE、Evidential Learning、MinHash、Grounding、Curriculum Learning
### 11.2 配置文件示例
#### 11.2.1 config.yaml核心配置：model/lora/environment/curriculum/reward/training/evaluation/checkpoint/demo/continual
### 11.3 环境依赖清单
#### 11.3.1 Python 3.10+、PyTorch 2.1+、Transformers 4.40+、Playwright 1.43+、PEFT 0.10+、TRL 0.8+、bitsandbytes 0.43+
### 11.4 部署Checklist
#### 11.4.1 环境准备→模型下载→数据准备→SFT训练→Progress Estimator训练→GRPO/PPO训练→评测→Demo部署

# 参考文献
## step_rl.agent.outline.md
- **Type**: 报告大纲
- **Description**: 本技术报告执行大纲
- **Path**: {workspace}/step_rl.agent.outline.md
