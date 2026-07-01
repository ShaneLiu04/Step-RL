
import re, os

base_path = r"C:\Users\ftlxy\Documents\【coding】\Step-RL\step-rl"
md_path = os.path.join(base_path, "Step-RL-v2.0-技术报告.md")

with open(md_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Titles for each diagram (1-15)
diagram_titles = [
    "图1-1：Step-RL v2.0 问题-方案-效果映射图",
    "图2-1：Step-RL v2.0 系统分层架构与数据流",
    "图2-2：Step-RL v2.0 上下游系统依赖关系",
    "图3-1：系统分层架构（五层）：接入层、业务层、控制层、优化层、数据层",
    "图3-2：Rollout / Update 两阶段协作流程",
    "图3-3：全数据流：观测 → 动作 → 校验 → 训练 → 评估",
    "图4-1：核心模块类图与继承关系",
    "图4-2：动作校验与修复时序图",
    "图4-3：课程状态机转换：L1 → L2 → L3 → L4",
    "图5-1：数据生命周期：从原始轨迹到评测输出",
    "图6-1：Web环境 + 稠密奖励 + 策略优化总览",
    "图7-1：部署拓扑：训练与推理分离",
    "图7-2：CI / CD 流水线：代码级与镜像级双阶段",
    "图9-1：消融实验递进路径：SFT 58% → GRPO 91%",
    "图10-1：v2.1 / v2.2 / v2.3 产品路线图",
]

# Gantt table replacement for diagram 11 (index 10)
gantt_table = """
| 阶段 | 任务 | 时间范围 | 依赖关系 |
|:---|:---|:---|:---|
| **v2.1 (Q1)** | 集成 trl 官方 Trainer | 2026-01 ~ 2026-03 | 无 |
| **v2.1 (Q1)** | 实现 PER 优先经验回放 | 2026-01 ~ 2026-02 | 无 |
| **v2.1 (Q1)** | 模型蒸馏至 1B 参数 | 2026-02 ~ 2026-04 | 无 |
| **v2.1 (Q1)** | 多模态融合（视觉 + 文本） | 2026-03 ~ 2026-05 | 无 |
| **v2.2 (Q2)** | DeepSpeed / FSDP 多卡分布式 | 2026-04 ~ 2026-06 | 无 |
| **v2.2 (Q2)** | Demo 人类反馈自动回传 | 2026-04 ~ 2026-05 | 无 |
| **v2.2 (Q2)** | 支持 Llama / Mistral 基座 | 2026-05 ~ 2026-07 | 无 |
| **v2.2 (Q2)** | 离线 RL 训练（静态轨迹） | 2026-06 ~ 2026-08 | 无 |
| **v2.3 (远期)** | 多智能体协作 | 2026-08 ~ 2026-10 | 依赖 v2.2.4 完成 |
| **v2.3 (远期)** | 世界模型（World Model） | 2026-10 ~ 2026-12 | 依赖 v2.3.1 完成 |

> **图10-1：v2.1 / v2.2 / v2.3 产品路线图**（甘特图转换为表格形式，因 Mermaid 甘特图语法在当前渲染环境中不兼容）
"""

mermaid_pattern = re.compile(r'```mermaid\n(.*?)\n```', re.DOTALL)
matches = list(mermaid_pattern.finditer(content))
print(f"Found {len(matches)} Mermaid blocks")

# Build replacement strings
replacements = []
for i, match in enumerate(matches):
    if i == 10:  # 11th diagram (0-indexed 10) - Gantt, no image
        replacements.append(gantt_table)
    else:
        # Map index to image number (skip 11)
        img_num = i + 1 if i < 10 else i + 2
        img_file = f"report_images/diagram_{img_num:02d}.png"
        title = diagram_titles[i]
        replacement = f"\n**{title}**\n\n![{title}]({img_file})\n"
        replacements.append(replacement)

# Replace from end to start to preserve positions
new_content = content
for i in range(len(matches) - 1, -1, -1):
    match = matches[i]
    new_content = new_content[:match.start()] + replacements[i] + new_content[match.end():]

# Save back
with open(md_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

# Verify
new_size = os.path.getsize(md_path)
new_lines = new_content.count('\n')
print(f"Saved. File size: {new_size} bytes, Lines: {new_lines}")

# Check how many image references we have
img_refs = new_content.count('![')
print(f"Image references in file: {img_refs}")

# Check that no mermaid blocks remain
remaining = list(mermaid_pattern.finditer(new_content))
print(f"Remaining Mermaid blocks: {len(remaining)}")
