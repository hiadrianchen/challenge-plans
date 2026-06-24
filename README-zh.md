# challenge-plans（中文）

[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue.svg)]()
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/hiadrianchen/challenge-plans/ci.yml?branch=main)](https://github.com/hiadrianchen/challenge-plans/actions)

> English: [README.md](README.md)

**在执行一份 plan/spec 之前，用你已登录的编码 CLI 对它做多 agent 对抗式评审。无需 API key。**

`challenge-plans` 编排你本机已有的订阅编码 CLI（Claude Code、Codex…）交叉拷问一份 plan/spec，把会导致后续返工的坑提前挖出来；拿不准时还能对多个选项投票。它也能审一份 `git diff`、当一次轻量 **code review**，并可作为 **agent skill** 接入。它跑在你已有的订阅上，没有按 token 的 API 费用。卡进 superpowers 计划生命周期：`writing-plans → challenge-plans → executing-plans`。

```text
$ challenge-plans run plan.md --type spec --profile standard --sink markdown

# challenge-plans · challenge · verdict: request_changes
- panel: expected 3 / collected 3 · complete ✓
- diversity: 2 families
- verified: 3 high/critical reviewed by Verifier (✓ verified, may hard-gate; ? unverified, advisory)
- surviving objections: 4

- [high✓]   sensitive data sent to a third-party LLM with no privacy boundary  @L42-43  (security_or_privacy_boundary, by claude:scope-boundary)
- [high✓]   "schema-aligned" claimed but there's no contract test             @L12-30  (integration_contract_gap, by gpt:correctness)
- [high✓]   no measurable acceptance threshold                               @L1      (contract_violation, by preflight)
- [medium?] missing_fields vs null semantics left undefined                  @L32-34  (ambiguity_to_wrong_implementation)
```

## 为什么用 challenge-plans

- 🔑 **无 API key、不按量计费** —— 驱动你已登录的订阅 CLI（Claude Code、Codex），至少有一个即可。
- 🧪 **证据胜过人数** —— 一条带可复现反证的少数派异议可以压过多数票；正确性不靠投票决定。
- 🤝 **跨家族验证** —— 一条异议只有当**另一个独立模型家族**用具体、带行锚的证据复现后，才获得硬 gate 资格（`✓`）；单模型声明只算 advisory。
- 🛡️ **内建防住 7 个多 agent 编排失败模式** —— 票据丢失、选项锚定、半途甩锅、多数压少数、单轮即收、虚假共识、假收敛。每一个都是开发本工具时用它自己的对抗流程真实踩中并修掉的。
- 🌍 **按你的语言输出** —— 源码是英文，但 `--lang zh`（或 `ja`、`de`、`fr`…）让每个评审都用你的语言写结论，而 JSON 键与行锚保持机器稳定。一个参数搞定，不另维护翻译版本 —— 见 [按你的语言输出](#按你的语言输出)。

## 快速开始

需要 Python ≥ 3.10（PyYAML 自动安装）。至少有一个已登录的编码 CLI —— **Claude Code**（`claude`）或 **OpenAI Codex**（`codex`）；两个不同厂商解锁跨家族验证。

```bash
git clone https://github.com/hiadrianchen/challenge-plans && cd challenge-plans
pip install -e .                                                          # 暴露 `challenge-plans` 命令
challenge-plans doctor                                                    # 看哪些后端 CLI 已登录
challenge-plans run examples/spec-sample.md --type spec --sink markdown   # 在自带样例上跑出一个 verdict
```

也可以把 repo 交给你的编码 agent —— *“从这个 repo 安装并配置好 challenge-plans，然后跑 `challenge-plans doctor`”* —— 它会替你做上面这些。**作为 agent skill**：把 [SKILL.md](SKILL.md) 放到你 agent 发现 skill 的目录即可。

## 使用

```bash
challenge-plans doctor                                                                 # 哪些后端就绪
challenge-plans run path/to/spec.md --type spec --profile standard --sink markdown     # 硬化一份 plan/spec
challenge-plans run change.diff --type diff --sink markdown                             # 审一份 git diff
challenge-plans weigh path/to/options.yaml --profile standard --sink markdown           # 在多个选项间投票
challenge-plans run path/to/spec.md --enforce                                           # CI gate：非 approve 退非零
challenge-plans run path/to/spec.md --type spec --sink markdown --lang zh                # 异议/证据用中文输出
# 未 pip 安装时前缀：PYTHONPATH=src python3 -m challenge_plans.cli ...
```

[`examples/`](examples/) 有可直接跑的样例（`spec-sample.md`、`options.yaml`）。`options.yaml`：
```yaml
question: 重构鉴权用方案 A 还是 B？
options:
  - id: A
    text: 一次性重写——风险集中但干净
  - id: B
    text: 渐进迁移——慢但每步可回滚
```

- `--profile fast|standard|deep`、`--sink stdout|markdown`、`--enforce`（非 approve 退非零；默认 advisory 退 0）。
- `--lang <代码>` 让人类可读输出用你的语言（默认 `en`）—— 见 [下文](#按你的语言输出)。
- `[sev✓]` = 跨家族已验证、可硬 gate；`[sev?]` = 未验证、仅 advisory。
- **artifact 类型：** `--type spec` 与 `--type diff` 均可用；`plan` / `decision` 保留（rubric 待补）。

bundled 的 [SKILL.md](SKILL.md) 自动把“审/QA 一份 plan/spec”路由到 `run`；投票走 `weigh` 子命令。

### 按你的语言输出

challenge-plans 源码是英文的，但评审可以用**任意**语言作答 —— 加上 `--lang` 即可：

```bash
challenge-plans run plan.md --type spec --lang zh     # 异议、证据、复现用中文
challenge-plans weigh options.yaml --lang ja          # 议事理由用日语
```

`--lang` 只切换**人类可读的文字**（steelman、标题、证据、复现、投票理由）。JSON 键、枚举值、`L12-15` 行锚保持原样，所以解析、去重、CI gate 都不受影响。等价于设一次 `CHALLENGE_PLANS_LANG`。没有另一份翻译版本要维护 —— 同一份英文源按需本地化。

**作为 agent skill：** agent 只要传 `--lang <用户语言>`，整份交叉 review 就用该语言返回。bundled 的 [SKILL.md](SKILL.md) 写明了这个参数，方便调用 agent 据用户语言自动设置。

## 两种模式

challenge-plans 不是单一功能，而是同一引擎上的两种模式。**调用 agent 按意图自动路由**，用户无需手动指定：

| | **对抗模式（challenge）** | **议事模式（weigh-options）** |
|---|---|---|
| 何时 | 有一份**成型的** plan/spec 要挑刺/硬化 | 有**几个选项 / 一堆 to-do** 拿不准选哪个 |
| 路由信号 | 单一成型 artifact + “帮我审/找漏洞/能不能执行” | 多个候选 + “选哪个/排序/值不值得做” |
| 聚合 | **证据存活制**：少数派可对，**禁多数投票** | **加权多数 + 暴露异议**：纯偏好取舍才投票 |
| 产出 | 六态 verdict + 存活异议 + 复现反证 | 排序选项 + 票数 + 最强异议 |

**模式由 agent 选、不甩给用户**：agent 读意图 → “审成型 artifact”走对抗、“在选项里挑”走议事，边界由确定性路由信号判定。议事中若某选项被标出**可机械验证的硬伤(blocker)**，推荐**降级为 `discuss` 并提示你去 challenge 模式核验**，而非径自采纳——所以投票永远压不掉能被证伪的少数派。

## 工作原理

**对抗模式**（reduce-rework loop）：
```
成型 artifact + bounded context
  → 多 persona/CLI challenger 各自 steelman→找漏洞(绑具体文本,禁hedging)
  → Verifier 跨家族出最小可复现反证 / 矛盾源行
  → 按 canonical key 去重 + 证据存活判定
  → 单一裁决管线出 verdict(六态) + 面板完整性核对
  →(--deep: 多轮到双条件收敛)
```

**议事模式** —— 方法论是标准三段。`weigh` CLI 实现第 ③ 段（对你给定的选项投票）；①② 段由调用 agent 在调用前负责，**禁止抄近路**：
```
① 背景对齐  (agent) 先给所有 voter 充分背景(待决问题/约束/已知信息), 不预设选项
② 意见收集  (agent) 各 voter 独立·互不可见·不被喂主控偏好地发散生成候选 → 去重聚类成选项池
③ 组织投票  `challenge-plans weigh` 对该选项池投票(model_family 加权防虚假共识) → 排序+票数+异议
           平票/缺票才交人, 否则完成闭环带回结果
```

## 它内建防住的 7 个多 agent 失败模式

这些坑是 naive 多 agent 编排几乎必踩的，也是我们**用对抗流程开发本工具时自己真实踩出来的**——每一个都被设计成机制挡住（dogfood 出来的护城河）：

1. **票据丢失**：challenger 输出被截断/超时/解析失败，系统静默拿残缺面板聚合。**防**：机械可读捕获 + 逐 voter 完整性自检；缺票绝不出 approve/宣布多数。
2. **选项锚定**：主控只抛自己预选的选项让大家投。**防**：议事必走“发散在前、投票在后”，voter 不被喂主控偏好。
3. **半途甩锅**：主控中途把开放决定甩回人工而不完成投票。**防**：完成闭环带回结果，仅平票/缺票才交人。
4. **多数压少数**：用多数投票否掉有可复现 blocker 的少数派真问题。**防**：两模式分治 + 串联逃逸门，对抗模式禁投票、证据压票数。
5. **单轮即收**：一轮对抗就宣布够了。**防**：`--deep` 多轮到收敛 + 写码前对代码再对抗。
6. **虚假共识**：同模型多 persona 的票被当独立票。**防**：按 model_family 加权封顶、raw/weighted 双显、单家族告警。
7. **假收敛**：某轮没新异议但旧 blocker 还 open 就宣布收敛。**防**：双条件收敛（new_surviving==0 且 unresolved_required==0）。

## 后端

challenge-plans 驱动你已登录的任一订阅编码 CLI —— 如 **Claude Code**（`claude`）或 **OpenAI Codex**（`codex`）。**不绑定任何特定一家。** 有**两个不同厂商**时可跨家族互验；只有一个时结论保持 advisory。无 API key、本工具不产生 per-token API 费用（`doctor` 只验登录、不查账单；用量仍计入你正常订阅额度）。

## 状态

**v1 — 可用。** 两模式端到端可跑，对真实 spec 验证过、由 pytest 套件钉住不变量，经多轮跨 agent 对抗 review 加固。

已知边界（输出里亦标）：concern 去重为精确锚点；无 idle-timeout（用墙钟）；议事 blocker 目前只标注、尚未自动转 Verifier 核验；开放决策的发散阶段由调用 agent 负责；`manual_paste`/Gemini adapter 为后续。

## 测试

```bash
pip install -e ".[dev]" && pytest      # pythonpath/testpaths 已配
```
测试套件钉住了历次对抗 review 确立的全部不变量。

## 贡献

欢迎 issue / PR —— 见 [CONTRIBUTING.md](CONTRIBUTING.md)。本项目 dogfood：开 PR 前用 `challenge-plans run <change>.diff --type diff` 审一遍自己的改动。

## 许可

[Apache-2.0](LICENSE)。
