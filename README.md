# Emotion LLM Lab

全球化情感陪伴 LLM 的微调研发闭环：以 Qwen3-8B 为底座，通过 SFT（人设注入）→
DPO（情感对齐）两阶段管线，在单张 NVIDIA A10G 上完成训练与推理部署。基础设施全量
IaC（AWS CloudFormation），数据合成与微调双仓库联动，**一个 repo 合成语料，另一个
repo 消费语料**，形成可重复的实验闭环。

---

## 🎯 项目定位

| 维度 | 选择 |
|---|---|
| 底座模型 | **Qwen3-8B-Instruct**（Apache 2.0，119 种语言原生覆盖） |
| 微调方法 | **QLoRA 4-bit** + **SFT → DPO** 两阶段对齐 |
| 框架 | LLaMA-Factory（训练） + Unsloth（加速后端） + vLLM（推理服务） |
| 训练硬件 | Amazon EC2 `g5.2xlarge`（1× A10G 24 GB），On-Demand 或 Spot |
| 本地开发 | MacBook（数据工程 + 评估 + MLX 本地推理验证） |
| 远程访问 | **AWS SSM Session Manager**，EC2 零公网入站 |
| 产物存储 | Amazon S3（SSE-S3、TLS-only、版本化） |
| Python | 3.11（本地） + 3.12（EC2，随 DLAMI），`uv` + PEP 735 dependency groups |

底座选型、对齐方法、基础设施形态的完整决策记录均在 [`docs/adr/`](./docs/adr/)，每一项都对标 2026 年的开源生态现状而非过时认知。

---

## 🔄 与上游数据合成仓库的闭环

本仓库与 [`ollama-gpu-host-aws`](https://github.com/ericyanpek/ollama-gpu-host-aws) 是**一体两仓**的设计。分仓的价值在于两个环境的生命周期完全不同——合成是按需短任务，训练是长对话式迭代——耦合在一起会相互污染。

```
┌──────────────────────────────────────┐         ┌────────────────────────────────────┐
│  ollama-gpu-host-aws                 │         │  emotion-llm-lab  （本仓）          │
│  （本仓的上游数据合成侧）              │         │                                    │
│                                       │ synth   │  LLaMA-Factory on EC2 g5.2xlarge   │
│  Ollama on EC2 g5/g6/g6e              │───────▶ │  ├─ SFT (persona injection)        │
│  ├─ Teacher: Gemma 4 / Qwen-Max 等    │   S3    │  ├─ DPO (emotional alignment)      │
│  ├─ 生成 SFT pair / DPO preference    │         │  ├─ Unsloth 2x 加速                │
│  └─ 持久化到 Amazon S3                │         │  └─ vLLM multi-LoRA serving        │
│                                       │         │                                    │
│  零 inbound / SSM-only / IAM 最小权限 │         │  零 inbound / SSM-only / IAM scoped│
└──────────────────────────────────────┘         └────────────────────────────────────┘
        ▲                                                          │
        └───────── 同一个 S3 artifact bucket 家族 ───────────────────┘
              （project-scoped IAM；跨仓只共享数据，不共享计算）
```

**闭环的三个重要属性：**

1. **Teacher 与 Student 物理隔离**：合成集群跑任意大型 Teacher 模型（Gemma 4 26B、Qwen-Max 等），训练集群只装 Student 训练栈；两边不会因为依赖冲突互相拖累。
2. **数据格式契约化**：合成侧直接产出 [LLaMA-Factory 兼容格式](https://github.com/hiyouga/LLaMA-Factory/blob/main/data/README.md)（Alpaca style SFT + Pairwise DPO），训练侧 `dataset_info.json` 直接指向 S3 URL，无中间转换脚本。
3. **DPO / KTO 双格式预留**：每条偏好样本同时写成 `chosen/rejected` 对（DPO 用）和 `binary label` 单标签（KTO 用）——数据采集一次成型，后续算法切换（DPO → KTO）无需重跑合成。参见 [ADR-0006](./docs/adr/0006-alignment-method-sft-dpo-with-kto-optional.md)。

### 典型的一次迭代

```bash
# ── ollama-gpu-host-aws 仓 ──
make deploy                              # g6e.xlarge on-demand 起 Ollama
./scripts/tunnel.sh                      # 端口转发 11434 到 Mac
python scripts/synth_sft.py              # 调 Ollama /api/chat 生成 3k 条 SFT
aws s3 sync data/ s3://emotion-companion-dev-artifacts/.../sft/
make destroy                             # 合成完立刻销毁，按小时计费

# ── emotion-llm-lab 仓（本仓）──
make start                               # 唤醒训练 EC2（不是首次部署）
# 编辑 configs/sft_qwen3_8b.yaml 指向刚合成的数据集
make tunnel                              # 浏览器 http://localhost:7860
# LLaMA-Factory webui 或 CLI 跑 SFT → 再跑 DPO
aws s3 sync saves/qwen3-8b-emotion-v1/ s3://.../adapters/
```

**下游完整链路未来延伸**：LoRA adapter 合并后用 vLLM `--enable-lora` 挂多个语种 adapter → FastAPI 网关路由 → 移动端 App。

---

## 🏛️ 技术亮点

### 1. 基础设施：零公网入站 + SSM 隧道访问

EC2 Security Group **零 inbound 规则**，连 SSH（22 端口）都不开。所有远程访问——
交互 shell、webui 端口转发、文件传输——全部经 AWS Systems Manager Session Manager
建立隧道：

- **IAM 鉴权**取代 SSH key 管理，配合 MFA 与 STS 临时凭证
- **无公网攻击面**：互联网扫描这台 EC2 的任何端口都会 DROP
- **CloudTrail 全量审计**：每次 session 建立、端口转发、命令下发都有记录
- **隧道只绑 `localhost`**：同 WiFi 网络里的其他设备扫不到 Mac 上的转发端口

出站规则同样做了端口限定（443 / 80 / 53 / 123），不是默认的 0.0.0.0/0 全开。
IMDSv2 强制、EBS 加密、S3 `BlockPublicAccess` + TLS-deny bucket policy 构成完整
的分层防御。详见 [ADR-0004](./docs/adr/0004-remote-access-ssm-session-manager.md)。

### 2. 双阶段 Bootstrap：UserData 只做最小化，复杂依赖走 SSM Document

一次踩过 UserData 的坑后就不想再踩：不可重试、失败 CFN 感知不到、debug 必须登机翻 log。新架构：

```
Phase 1 (UserData, ~5 min)   CloudWatch agent + 环境变量 + auto-shutdown cron + marker
Phase 2 (SSM Document, ~15 min, idempotent, CloudWatch Logs)   uv + LLaMA-Factory + vLLM
```

SSM Document 幂等可重跑，每一步有独立 exitcode 与结构化日志。参见 [ADR-0007](./docs/adr/0007-bootstrap-via-ssm-document.md)。

### 3. 依赖管理：PEP 735 dependency groups + 三环境分离

```
Mac   .venv  (local + eval + dev)     数据工程 / MLX 本地推理 / LLM-as-judge
EC2   ~/venv-train (train)            LLaMA-Factory + Unsloth 训练
EC2   ~/venv-serve (serve)            vLLM 推理（与 train 隔离）
```

`uv` 统一三环境，锁文件 `uv.lock` 保证跨机复现性。参见 [ADR-0005](./docs/adr/0005-python-311-uv-dependency-groups.md)、[ADR-0008](./docs/adr/0008-train-venv-self-contained-torch.md)。

### 4. 双层 GPU 闲置自动关机

| 层 | 机制 | 触发条件 |
|---|---|---|
| Layer 1 | EC2 内 cron（每 15 min） | GPU util <5% **且** GPU mem <1GB **且** 无活跃 SSM session 持续 1 小时 |
| Layer 2 | CloudWatch alarm | `nvidia_gpu_utilization_gpu` 指标 <5% 持续 60 分钟，触发 `ec2:stop` |

互不依赖：Layer 1 死了 Layer 2 兜底；反之亦然。任意一层触发后实例 stop（不是 terminate），EBS + 训练栈保留，2 分钟可唤醒。

### 5. 多语言对齐的工程化路径

Qwen3 原生 119 种语言 → PoC 阶段三语种落地（英 / 西 / 中，覆盖全球约 55% 人口）→ vLLM multi-LoRA serving 每个语种独立 adapter。数据分层采样（`interleave_under`），DPO 按语种独立评估 reward margin，避免全局 loss "假阳性"遮掩小语种退化。

### 6. 每一个"不常见的选择"都有 ADR 背书

10 份 ADR 覆盖底座选型、框架选型、硬件、远程访问、Python 环境、对齐方法、bootstrap 模式、torch 版本约束 等。**6 个月后你仍能知道为什么当初这么定。** 参见 [docs/adr/README.md](./docs/adr/README.md)。

---

## 🚀 快速上手

### 前置

```bash
brew install awscli
brew install --cask session-manager-plugin
brew install shellcheck
aws sts get-caller-identity
```

账号需具备 "Running On-Demand G and VT instances" vCPU 配额 ≥ 8（g5.2xlarge）。

### 首次部署

```bash
# 本地 dev 环境
make sync                                # uv 安装 local + eval + dev 依赖
source .venv/bin/activate

# 预检（15 项检查，30 秒内判断能否 deploy）
make preflight

# Phase 1：CFN 建栈（~5 min）
make deploy

# Phase 2：训练栈安装（~15 min，幂等可重跑）
make bootstrap

# 设置 Hugging Face token（写入 SSM Parameter Store SecureString）
make secrets
```

完整路径与故障树见 [docs/runbooks/first-deploy.md](./docs/runbooks/first-deploy.md)。

### 日常流程

```bash
aws ec2 start-instances --instance-ids <id> --region us-east-1   # 唤醒
make tunnel                                                       # 三端口转发
# 浏览器:
#   LLaMA-Factory webui  http://localhost:7860
#   TensorBoard          http://localhost:6006
#   vLLM OpenAI API      http://localhost:8000
```

用完 1 小时自动 stop，或 `aws ec2 stop-instances ...` 立即关。

### 完整销毁

```bash
make destroy   # 保留 S3 artifacts，其他资源全部清理
```

---

## 🗂️ 仓库结构

```
.
├── pyproject.toml            # Python 3.11 + uv + PEP 735 groups (local / eval / train / serve / dev)
├── uv.lock                   # 依赖锁文件，已 commit
├── .python-version           # 3.11 本地锁定
├── Makefile                  # 统一入口：sync / preflight / deploy / bootstrap / tunnel / destroy
├── infrastructure/
│   ├── cloudformation/
│   │   └── training-env.yaml # VPC BYO + EC2 + SG + S3 + SSM Document + CloudWatch Alarm + Budget
│   └── scripts/
│       ├── preflight.sh      # 预检：凭证 / 配额 / AMI / 命名冲突 / IAM smoke（STRICT=1）
│       ├── deploy.sh         # 建 / 更新栈，自动识别 Default VPC
│       ├── bootstrap.sh      # 触发 SSM Document 装训练栈，流式监控
│       ├── tunnel.sh         # 多端口 SSM 端口转发（每端口一个子进程 + 清理 trap）
│       ├── set-secrets.sh    # 交互式写入 SSM Parameter Store SecureString
│       ├── ssm-shell.sh      # SSM 交互式 shell
│       └── destroy.sh        # 带确认的 delete-stack
├── configs/                  # LLaMA-Factory SFT / DPO YAML
│   ├── sft_qwen3_8b_smoke.yaml  # SFT 10 步烟雾测试
│   ├── sft_qwen3_8b_v1.yaml     # SFT 真训练模板
│   ├── dpo_qwen3_8b_smoke.yaml  # DPO 10 步烟雾测试（基于 SFT adapter）
│   └── dpo_qwen3_8b_v1.yaml     # DPO 真训练模板
├── data/                     # 训练数据（tiny 样本提交仓库；真实规模走 S3）
│   ├── dataset_info.json     # LLaMA-Factory 数据清单
│   ├── sft/ dpo/             # Alpaca-style 样本文件
│   └── README.md
├── personas/                 # 人设文档（每语种一份）
│   ├── _template.md
│   └── lily_warm_companion_en.md
├── schemas/                  # JSON Schema（与上游合成仓的数据契约）
│   ├── sft_alpaca.schema.json
│   └── dpo_alpaca.schema.json
├── scripts/                  # 数据前处理 / 评估脚本（待落地）
└── docs/
    ├── adr/                  # 10 份 Architecture Decision Records
    └── runbooks/
        └── first-deploy.md   # 首次部署手册 + 踩坑记录
```

---

## 📐 当前状态与路线图

- [x] 基础设施：CFN 模板 + SSM 隧道脚本
- [x] Python 环境：pyproject + uv + Python 3.11 pin
- [x] 开发工具：Makefile、pre-commit、ruff、pyright、shellcheck、cfn-lint、CI
- [x] 决策档案：10 份 ADR
- [x] 实机验证：CFN 建栈 / SSM 连通 / uv + LLaMA-Factory + Unsloth + vLLM 全绿
- [x] Webui 真机打通：Mac 浏览器通过 SSM 隧道访问 `localhost:7860` → HTTP 200
- [x] 数据 schema 与 `dataset_info.json`：Alpaca-style SFT + DPO，5+5 条 tiny 样本，JSON Schema 验证通过
- [x] 首份 persona 文档：Lily（英语版，含身份探针、边界规则、system prompt）
- [x] SFT 训练配置：`sft_qwen3_8b_smoke.yaml`（10 步烟雾测试）+ `sft_qwen3_8b_v1.yaml`（真训练模板，字段差异逐行注释）
- [x] 首次 SFT smoke 训练：10 步 loss 5.03 → 0.78，167MB LoRA adapter 落盘
- [x] DPO 训练配置：`dpo_qwen3_8b_smoke.yaml`（基于 SFT adapter + reference-free）+ `dpo_qwen3_8b_v1.yaml`（真训练模板）
- [ ] 首次 DPO smoke 训练：在 EC2 上跑通 10 步，rewards/margins 为正
- [ ] 多语言 persona：Lily 中文版（`lily_warm_companion_zh.md`）
- [ ] DPO 训练配置：reference-free 模式 + 多语种分桶评估
- [ ] 评估管线：LLM-as-judge + persona drift probe + code-switching 检测
- [ ] vLLM multi-LoRA serving + FastAPI 网关

---

## 🔑 关键设计决策速览

| ID | 标题 | 状态 |
|---|---|---|
| [0001](./docs/adr/0001-base-model-qwen3-8b.md) | Qwen3-8B 作为底座（Apache 2.0 + 119 种语言） | Accepted |
| [0002](./docs/adr/0002-fine-tune-framework-llama-factory.md) | LLaMA-Factory + Unsloth（SFT 加速）+ TRL（DPO） | Accepted |
| [0003](./docs/adr/0003-training-hardware-ec2-g5-dlami.md) | EC2 g5.2xlarge + DLAMI PyTorch 2.7 | Accepted |
| [0004](./docs/adr/0004-remote-access-ssm-session-manager.md) | SSM Session Manager，零公网入站 | Accepted |
| [0005](./docs/adr/0005-python-311-uv-dependency-groups.md) | Python 3.11 + uv + PEP 735 groups | Accepted（部分由 0008 supersede） |
| [0006](./docs/adr/0006-alignment-method-sft-dpo-with-kto-optional.md) | SFT → DPO，保留 KTO 路径 | Accepted |
| [0007](./docs/adr/0007-bootstrap-via-ssm-document.md) | 训练栈安装走 SSM Document，非 UserData | Accepted |
| [0008](./docs/adr/0008-train-venv-self-contained-torch.md) | Train venv 自建 torch 栈（不复用 DLAMI） | Accepted |
| [0009](./docs/adr/0009-unsloth-pins-torch-version.md) | Unsloth 决定 torch 版本（2.10.0+cu128 精确钉） | Accepted |
| [0010](./docs/adr/0010-secrets-never-baked-into-scripts.md) | Secrets 仅通过环境变量，绝不 bake 进脚本 | Accepted |

---

## 💰 成本参考（us-east-1，On-Demand）

| 资源 | 单价 / 月 |
|---|---|
| g5.2xlarge 每天 8 小时 × 20 天 | ~$190 |
| g5.2xlarge 24×7 | ~$880 |
| EBS 500GB gp3 | ~$40 |
| S3（50 GB artifacts） | ~$1 |
| CloudWatch 日志 / 指标 | ~$2 |
| **典型 PoC（8h × 20d）** | **~$235** |

Spot 可将 EC2 成本再降 60%；`AutoShutdownHours=1` 默认保护空闲烧钱。

---

## 📜 License

代码使用 MIT License。模型权重与数据遵循各自 License（Qwen3 Apache 2.0，LLaMA-Factory Apache 2.0，自产数据归属你自己）。

---

> **一句话定位：** 一个为"全球化情感陪伴 App"而生的 LLM 微调 lab，与上游数据合成仓库
> [`ollama-gpu-host-aws`](https://github.com/ericyanpek/ollama-gpu-host-aws) 联动，在 IaC、Well-Architected 安全基线、
> 和工程决策可追溯性三个维度同时做到"生产级 PoC"。
</content>
