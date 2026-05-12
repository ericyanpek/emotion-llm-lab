# Learning Plan · 以项目为抓手的理论回补与前沿引导

> 这不是一份"从零入门"的大纲,而是围绕 emotion-llm-lab 项目的一张索引:
>
> - **已经做的**:从学习规划里找对应的**理论回补**,把直觉变成可解释的选择
> - **接下来要做的**:从学习规划里找对应的**前沿引导**,学到能判断方案、能读懂 PR、能避开已知坑就足够

**交互版(可勾选打卡)**:`~/Desktop/LLM-Post-Training-学习规划.html`
**本 MD 版**:版本化的"正本",与 HTML 保持内容一致,更新时两边同步。

---

## 项目上下文速览

| 维度 | 决策 | ADR |
|---|---|---|
| 底座模型 | Qwen3-8B-Instruct | [ADR-0001](../adr/0001-base-model-qwen3-8b.md) |
| 对齐方法 | SFT → DPO(KTO 路径保留) | [ADR-0006](../adr/0006-alignment-method-sft-dpo-with-kto-optional.md) |
| 训练栈 | LLaMA-Factory + Unsloth + TRL + QLoRA 4-bit | [ADR-0002](../adr/0002-fine-tune-framework-llama-factory.md) |
| 硬件 | EC2 g5.2xlarge(1× A10G 24GB) | [ADR-0003](../adr/0003-training-hardware-ec2-g5-dlami.md) |
| 评估管线 | 4 维 rubric + LLM-as-judge + 确定性 drift-probe 护栏 | [ADR-0011](../adr/0011-eval-pipeline-llm-as-judge-plus-drift-probes.md) |
| 推理 | vLLM multi-LoRA + FastAPI 网关(规划中) | — |
| 场景 | 全球化情感陪伴(英/西/中三语种 PoC) | — |

---

## PART 1 · 回补理论映射

项目里已经落地或正在跑的东西,回头把对应的理论基础读一遍。

---

### M1 · 底座选型 & 对齐路线 · `ADR-0001 / ADR-0006`

**状态**:✅ 已落定
**项目决策**:Qwen3-8B(Apache 2.0,119 种语言)作为底座,SFT → DPO 两阶段对齐,KTO 路径在数据 schema 里预留。

**回补资源**:

- [ ] **[RLHF Book · 第 3–7 章](https://rlhfbook.com)** · 教科书
  Nathan Lambert。把 Pretrain → SFT → Reward Model → PPO → DPO → Preference Optimization 全链路一次性讲透。你已经在跑 DPO,回头读能补齐"为什么是这条路径"的系统认知。
- [ ] **[DPO 原始论文 · Rafailov et al. 2023](https://arxiv.org/abs/2305.18290)** · 论文
  重点看 reward modeling → Bradley-Terry → policy ratio 的闭式解推导。理解之后 YAML 里 `beta`、`reference_free` 不再是魔法参数。
- [ ] **[KTO 论文 · Ethayarajh et al. 2024](https://arxiv.org/abs/2402.01306)** · 论文
  ADR-0006 保留了 KTO 路径,schema 也预留了 binary label 格式。读原论文理解"为什么只需要单标签就能做偏好对齐",以及什么情况下该切到 KTO(偏好对噪声大或标注成本高时)。
- [ ] **[Qwen3 技术报告](https://qwenlm.github.io/blog/qwen3/)** · 技术报告
  你的底座。读它自己的 post-training 描述、chat template、多语言训练策略。避免你做的对齐和官方已经做过的冲突。

---

### M2 · 训练栈架构 · `ADR-0002 / ADR-0008 / ADR-0009`

**状态**:✅ 已落定
**项目决策**:LLaMA-Factory(训练)+ Unsloth(加速)+ TRL(DPO 底层)+ QLoRA 4-bit,torch 2.10.0+cu128 精确钉。

**回补资源**:

- [ ] **[TRL 源码 · DPOTrainer / SFTTrainer](https://github.com/huggingface/trl/tree/main/trl/trainer)** · 源码
  LLaMA-Factory 的 DPO 就是 wrap 这里。对照 YAML 里 `pref_beta`、`pref_loss`、`pref_ftx` 看实际计算图,知道每个参数落到哪一行代码。
- [ ] **[LLaMA-Factory examples/](https://github.com/hiyouga/LLaMA-Factory/tree/main/examples)** · 示例
  比任何教程都贴近你的实际操作——你的 `configs/` 就是这个格式。把 examples 里 SFT / DPO / KTO 的所有 YAML 对比一遍,知道哪些字段你还没用到。
- [ ] **[PEFT 官方文档 · LoRA 深入](https://huggingface.co/docs/peft)** · 文档
  LoRA rank / alpha / target_modules / rslora / dora 的官方解释。校准你 configs 里的 LoRA 设置是否最优。
- [ ] **[QLoRA 论文](https://arxiv.org/abs/2305.14314)** + **[Tim Dettmers · GPU 选型](https://timdettmers.com/2023/01/30/which-gpu-for-deep-learning/)** · 论文+博客
  你在用 4-bit。读原论文理解 NF4 quantization、double quantization、paged optimizer。A10G 24GB 能训 Qwen3-8B 的显存预算为什么够,这里算清楚。
- [ ] **[Unsloth 博客 · 2x 加速的来源](https://unsloth.ai/blog)** · 博客
  手写 Triton kernel + 梯度检查点重构 + LoRA 算子融合。知道 ADR-0009 里为什么 torch 版本必须跟着 Unsloth 走。

---

### M3 · SFT / DPO Smoke 已跑通 · `configs/*_smoke.yaml`

**状态**:✅ 已完成
**项目状态**:10 步 SFT smoke loss 5.03 → 0.78,167MB LoRA adapter 落盘。10 步 DPO smoke rewards/margins 为正,基于 SFT adapter + reference-free。

**回补资源**:

- [ ] **[Llama 3 技术报告 · Post-Training 章节](https://ai.meta.com/research/publications/the-llama-3-herd-of-models/)** · 技术报告
  92 页,最完整公开的 SFT→DPO recipe。看真实工业 scale 下的数据量、epochs、β、data filtering,校准你从 smoke 升到 v1 时该怎么选参数。
- [ ] **[Tülu 3 · 完全开源的 post-training recipe](https://allenai.org/blog/tulu-3)** · recipe
  Ai2 的 SFT → DPO → RLVR 完整开源:数据、代码、config、训练日志全公开。现阶段最直接能抄的参考。
- [ ] **[Interconnects · DPO 主题合集](https://www.interconnects.ai/t/dpo)** · 博客
  Nathan Lambert 写过十几篇 DPO 实战观察:β 取值、reference model 的影响、DPO 失败模式。从 smoke 升 v1 之前全部扫一遍。

---

### M4 · 数据契约 & Persona 设计 · `schemas/ · personas/`

**状态**:✅ 已落地
**项目状态**:Alpaca-style SFT + Pairwise DPO JSON Schema 已写,Lily(英语版)首份 persona 含身份探针、边界规则、system prompt。双仓通过同一个 S3 bucket 传数据。

**回补资源**:

- [ ] **[Self-Instruct · 合成数据祖师爷](https://arxiv.org/abs/2212.10560)** · 论文
  上游仓用 Ollama Teacher 合成 SFT 数据,方法论源头就是这篇。知道 seed instructions / diversity filtering 的原理,判断合成数据是否够多样。
- [ ] **[UltraFeedback · 偏好数据标注范式](https://arxiv.org/abs/2310.01377)** · 论文
  DPO 的 chosen/rejected 对,生成范式最值得抄的就是它:多模型回答 + 多维度打分 → 自动构造 preference pair。合成管线下一步可以借鉴。
- [ ] **[Anthropic · Claude's Character](https://www.anthropic.com/news/claude-character)** · 官方博客
  personas/Lily 的"身份探针 + 边界规则 + system prompt"三件套,业内最系统化的同类工作就是 Anthropic 的 character training。对比能看出哪些部分还可以再细化。
- [ ] **[Constitutional AI · Anthropic](https://arxiv.org/abs/2212.08073)** · 论文
  persona 边界规则再往上一层:把人设规则变成可训练的 constitution。将来想把 persona drift 从 probe 变成训练目标,这是方法论基础。

---

## PART 2 · 前沿引导路径

项目 roadmap 里 TODO 的事情,每件都对应一条学习路径。

---

### G1 · 从 Smoke 到 v1 真训练 · `configs/*_v1.yaml`

**状态**:🟡 即将开始
**项目 TODO**:SFT v1 和 DPO v1 的真训练。关键决策:**超参怎么选、β 怎么调、epoch 多少、loss 类型选 sigmoid / ipo / simpo**。

**引导资源**:

- [ ] **[IPO 论文](https://arxiv.org/abs/2310.12036)** + **[SimPO 论文](https://arxiv.org/abs/2405.14734)** · 论文
  DPO 的两个改良:IPO 解决 overfitting,SimPO 去掉 reference model。TRL 里 `loss_type` 可直接切换。
- [ ] **[HF · Preference Tuning 对比实验](https://huggingface.co/blog/pref-tuning)** · 博客
  DPO / IPO / KTO 在相同 setup 下的直接对比。做 v1 选型最有参考价值。
- [ ] **[Nathan Lambert · DPO 无参考模型](https://www.interconnects.ai/p/dpo-without-reference-model)** · 博客
  smoke 用的就是 reference-free,读这篇知道这个选择的代价是什么、什么时候应该加回 reference。

---

### G2 · 多语言对齐 · `personas/*_zh.md · interleave_under`

**状态**:🟣 进行中
**项目 TODO**:Lily 中文版 persona、三语种数据分层采样、DPO 按语种独立评估 reward margin。
**难点**:小语种数据少易被大语种淹没,全局 loss 会掩盖小语种退化。

**引导资源**:

- [ ] **[Qwen3 技术报告 · 多语言训练细节](https://arxiv.org/abs/2505.09388)** · 技术报告
  Qwen3 自己的 multilingual alignment 策略。你在它基础上再对齐,必须知道它已经做了什么。
- [ ] **[Self-Rewarding · 跨语言泛化](https://arxiv.org/abs/2404.05868)** · 论文
  偏好对齐能跨语言迁移的实证。帮你判断"用英文偏好对训,中文能不能免费受益"。
- [ ] **[Aya · 多语言 SFT 大规模实证](https://arxiv.org/abs/2404.00399)** · 论文
  Cohere For AI 的 Aya 项目,101 种语言 SFT 实战。重点看数据分层采样、code-switching 处理、小语种评测方法。

---

### G3 · 评估管线 · `scripts/eval/ · configs/eval/rubric_v1.yaml · ADR-0011`

**状态**:🟡 骨架已就绪,等真机接入
**项目现状**(ADR-0011 已 Accepted):
- **4 维 rubric**(voice / emotional_register / identity / boundaries)对齐 persona 模板
- **确定性 hard-reject 护栏** — 检出"As an AI language model..."这类已知失败模式,弥补 judge 盲区
- **probe_type 与 DPO schema 共享 enum** — 一个 drift 可追溯到应该修复它的 DPO pair
- **stub + real 双后端** — `make eval-dry` 无 GPU 无 API key 秒级跑完 CI
- **PR-ready 报告** — `outputs/eval/<run_id>/{summary.md, summary.json}`

**剩余 TODO**:vLLM serving → 真实 adapter 跑 probes、多语种 code-switching 检测、按语种 reward-margin 分桶

**引导资源**(理解 B 已搭好的骨架 + 为下一步扩展做准备):

- [ ] **[lm-evaluation-harness · 通用能力保底](https://github.com/EleutherAI/lm-evaluation-harness)** · 工具
  B 的 eval 专注 persona / 情感质量。MMLU / GSM8K / HellaSwag 这一层是"通用能力有没有塌",两者互补。ADR-0011 的 rubric 不覆盖这块——值得作为独立 eval track 加上。
- [ ] **[MT-Bench · LLM-as-Judge 范式](https://github.com/lm-sys/FastChat/blob/main/fastchat/llm_judge/README.md)** · 工具
  B 已做到 LLM-as-judge + 1-5 rubric。MT-Bench 的"已知 judge 偏差"文档化(长度偏差、立场偏差、自打分偏差)是校准 B 的 Claude judge 时的必读参考。
- [ ] **[Arena-Hard · 裁判校准方法](https://lmarena.ai/blog/arena-hard)** · 博客
  当 B 开始用 Claude 和 GPT-4o cross-check 时(ADR-0011 提到 OpenAI as tiebreaker),裁判校准方法直接对口。
- [ ] **[Lilian Weng · Reward Hacking](https://lilianweng.github.io/posts/2024-11-28-reward-hacking/)** · 教科书级
  系统讲 judge / reward model 被 hack 的模式。B 的 hard-reject 机制是在工程侧对抗这类风险,理论侧读 Lilian 能看到更深的失败模式(语义改写绕过、judge 自我欺骗等)。
- [ ] **[ADR-0011 本身](../adr/0011-eval-pipeline-llm-as-judge-plus-drift-probes.md)** · 项目内
  B 写的 Alternatives Considered 部分(为什么不用分类器 / 为什么不用纯 A/B judging / 为什么不加到 7+ 维)值得作为独立学习材料读一遍——工程决策的思维路径在这里。

---

### G4 · 情感 AI 安全与对齐 · `personas/边界规则`

**状态**:🔴 核心风险项
**项目特有风险**:情感陪伴场景最容易出 **sycophancy(讨好型回答)、回避现实、过度迎合**。这是 emotion-llm-lab 区别于通用 SFT 的核心难点,也是产品成败关键。

**引导资源**:

- [ ] **[Sycophancy in LLMs · Anthropic](https://arxiv.org/abs/2310.13548)** · 论文
  讨好型回答的系统性研究:成因、检测、缓解。情感陪伴 App 最可能翻车的地方——用户说什么都附和,短期满意长期有害。
- [ ] **[EmpatheticDialogues · 25k 情感对话](https://huggingface.co/datasets/facebook/empathetic_dialogues)** · 数据集
  场景最对口的公开数据集。可用来扩充 SFT,或做情感响应的 held-out 评测。标注偏单轮,不完全等同于陪伴场景。
- [ ] **[GoEmotions · 27 类情绪标注](https://github.com/google-research/google-research/tree/master/goemotions)** · 数据集
  要做"检测用户当前情绪 → 调整回应",这是标注最细的开源情绪数据集。可训辅助情绪分类器做 probe。
- [ ] **[Persona Drift 研究 · Role-Play Evaluation](https://arxiv.org/abs/2310.03051)** · 论文
  roadmap 里 "persona drift probe" 的学术参考。理解长对话中人设怎么崩的、怎么测。对 Lily 身份稳定性评估最直接相关。

---

### G5 · vLLM multi-LoRA Serving + FastAPI 网关 · `roadmap TODO`

**状态**:🔴 部署侧
**项目 TODO**:三语种 LoRA adapter 在同一个 vLLM 服务上热切换,FastAPI 网关做路由。
**决策点**:每个 adapter 独立进程还是共享推理?显存怎么分?

**引导资源**:

- [ ] **[vLLM Multi-LoRA 官方文档](https://docs.vllm.ai/en/latest/features/lora.html)** · 文档
  直接对应 roadmap。重点看 `--enable-lora`、`--max-loras`、`--max-lora-rank`,以及动态加载 adapter 的 API。
- [ ] **[vLLM 博客 · 推理优化系列](https://blog.vllm.ai/2024/07/23/llama31.html)** · 博客
  paged attention、continuous batching、prefix caching 的原理。A10G 上做多语种 serving 必须算清吞吐预算。
- [ ] **[Philipp Schmid · AWS 上推理部署实战](https://www.philschmid.de/)** · 博客
  基础设施在 AWS,Philipp 长期写 AWS+HF 生态的实战教程。vLLM 在 EC2 / SageMaker 上的部署坑他都踩过。

---

### G6 · 合成数据持续优化 · 与 ollama-gpu-host-aws 联动

**状态**:🟣 上游演进
**项目现状**:上游用 Ollama Teacher(Gemma 4 / Qwen-Max 等)合成 SFT + DPO 数据。
**下一代方向**:从"随机生成"升级到"按 weakness 定向补数据"、自蒸馏、RLAIF。

**引导资源**:

- [ ] **[Magpie · 自蒸馏合成数据](https://arxiv.org/abs/2406.08464)** · 论文
  2024 年最有影响的合成方法:直接从对齐模型里"榨"出高质量 instruction-response 对,零种子。上游合成管线下一代升级路径。
- [ ] **[RLAIF · 用 AI 替代人类标注偏好](https://arxiv.org/abs/2309.00267)** · 论文
  你目前合成 chosen/rejected 的做法就是 RLAIF 雏形。读原论文理解它相比 RLHF 的代价和边界。
- [ ] **[mlabonne/llm-datasets · 数据集地图](https://github.com/mlabonne/llm-datasets)** · 索引
  post-training 公开数据集索引。觉得"自己合成的不够多样"时翻一下,经常能找到现成可混入的高质量数据。

---

## PART 3 · 长期订阅

每周 1 小时跟进前沿,避免知识过时。这几位信噪比最高,不是新闻号而是真在一线做。

- [ ] **[Interconnects · Nathan Lambert](https://www.interconnects.ai/)** — post-training 第一博客,Ai2 Tülu/OLMo 团队一线观察
- [ ] **[Lilian Weng](https://lilianweng.github.io/)** — 更新慢但每篇教科书级
- [ ] **[Ahead of AI · Sebastian Raschka](https://magazine.sebastianraschka.com/)** — 工程细节最清晰,代码示例密集
- [ ] **[Philipp Schmid](https://www.philschmid.de/)** — AWS + HF 生态对口

---

## 使用心法

- 回补不是"必须按顺序学完",而是遇到卡壳时回来查对应的 Milestone
- 引导不是"学完才能动手",而是"学到能判断方案"就足够
- 每完成一个 roadmap 项,在对应的 Milestone 下写一页 ADR 记录最终方案
- **评估(G3)比训练本身更重要**——没评估的训练都是自嗨
- **情感安全(G4)是护城河**,别当 nice-to-have

## 建议优先级

| 时间窗口 | 重点 |
|---|---|
| 本周 | G1 + M3(DPO 论文 + 真训练准备) |
| 下周 | **G3 真机接入**(ADR-0011 骨架已就绪,用真实 adapter 产出首份质量报告) |
| 并行 | G4 sycophancy 论文(核心风险,直接喂给 B 扩充 hard_rejects 库) |
| v1 训练稳定后 | G2 多语言 + G5 vLLM serving |
| 长期 | G6 合成数据演进(决定效果天花板) |

---

## 文档维护约定

- **本 MD 是正本**,桌面 HTML 是可交互副本。内容不一致时以 MD 为准。
- 勾选状态只存在于 HTML(浏览器 localStorage),MD 中的 `- [ ]` 作为静态清单。
- 新增资源或新 milestone:先改 MD,再同步到 HTML(两份结构对齐)。
- 每完成一个 milestone 的主要阅读,可在下面留一段 3-5 行的"读后感"或链接到对应 ADR。
