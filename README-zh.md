# challenge-plans（中文）

[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue.svg)]()
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/hiadrianchen/challenge-plans/ci.yml?branch=main)](https://github.com/hiadrianchen/challenge-plans/actions)

> English: [README.md](README.md)

**在执行一份计划之前，用你已登录的 AI 编码 CLI 对它做对抗式评审。无需 API key。**

`challenge-plans` 编排你本机的订阅 CLI（Claude Code、Codex…）交叉拷问一份计划，把会导致返工的坑提前挖出来——再把**经得起推敲、存活下来**的异议聚合成一个 verdict。它可以当 CLI、当 **agent skill**、当 CI gate 用，并卡进 superpowers 计划生命周期：`writing-plans → challenge-plans → executing-plans`。

## 为什么用 challenge-plans

- 🔑 **无 API key、不按量计费** —— 驱动你已登录的订阅 CLI（Claude Code、Codex），至少有一个即可。
- 🧪 **证据胜过人数** —— 一条带可复现反证的少数派异议可以压过多数票；正确性不靠投票决定。
- 🤝 **跨家族验证** —— 一条异议只有当**另一个独立模型家族**用带行锚的证据复现后，才获得硬 gate 资格（`✓`）；单模型声明只算 advisory。
- 🛡️ **内建防住 7 个多 agent 失败模式** —— 票据丢失、选项锚定、半途甩锅、多数压少数、单轮即收、虚假共识、假收敛（[详见](docs/how-it-works.md)）。
- 🌍 **说你的语言** —— `--lang zh`（或 `ja`、`de`…）把每条结论本地化；一个参数搞定，不另维护翻译版本。

## 它能审什么

你不写 spec 也能用。它做四件事：

- 📋 **任何计划** —— 旅行、上线、招聘、搬家。`--type plan` 按「计划常见错法」来挑刺（见下）。
- 📝 **一份成型的 spec / 设计稿**（动手前）—— `--type spec`。
- 🔧 **一次代码改动**（轻量 review）—— `--type diff`。
- 🧭 **一个你已经做出的决定** —— 技术选型、选供应商、招人。`--type decision` 审**这个决定本身**：你跳过的替代方案、撑不起赌注的证据、沉没成本式论证、回不了头的步骤。

而当你**在几个还没定的选项间拿不准**时，`weigh` 用加权、暴露异议的议事来投票选。

## 快速开始

**最省事——交给你的 agent。** 对它说：

> 从 https://github.com/hiadrianchen/challenge-plans 安装 challenge-plans，然后跑 `challenge-plans doctor`。

它会装好包并报告哪些后端就绪。

**或者自己装**（Python ≥ 3.10）：

```bash
pip install challenge-plans      # 或：pipx install challenge-plans  ·  uvx challenge-plans doctor
challenge-plans doctor           # 看哪些 CLI 已登录
```

至少有一个已登录的 CLI —— **Claude Code**（`claude`）或 **OpenAI Codex**（`codex`）；两个不同厂商解锁跨家族验证。**作为 agent skill**：把 [SKILL.md](SKILL.md) 放到你 agent 发现 skill 的目录。（要改源码？`git clone … && pip install -e .`。）

## 看它跑

下面是「**任何计划**」这一种情形——上面四种之一——用在一份粗糙的京都旅行攻略上（[`examples/plan-sample.md`](examples/plan-sample.md)）：

```text
$ challenge-plans run examples/plan-sample.md --type plan --sink markdown

# challenge-plans · challenge · verdict: request_changes
- [high✓] 机票不可退，却在验证行程之前就锁死了        @L10  (irreversibility_or_high_cost, by claude:feasibility)
- [med ] Day2 横跨全城塞了 6 个景点，基本走不完        @L4   (ignored_constraint, by gpt:risk)
- [med ] 从没定义「什么算一趟好旅行」，无从判断行程好坏  @L1   (missing_success_criteria, by claude:goal-alignment)
```

每一行是一条**贴了标签的异议**——绑到具体行、由某个只管一件事的评审提出。上面三条就来自三个评审：

- **可行性** *（现实里能不能落地？）* → 抓到**机票不可退**却在行程还没验证前就锁死。
- **风险** *（哪最可能出错 / 不可逆？）* → 抓到 **Day2 横跨全城塞了 6 个景点**、没有时间预算。
- **目标对齐** *（步骤能达成目标吗？）* → 抓到**从没定义「什么算一趟好旅行」**，于是无从判断。

每条异议都从一份固定的「**计划可能错在哪**」清单里选标签——这让每条都具体、可去重。每个标签放到这趟旅行上会抓到什么：

- `irreversibility_or_high_cost` —— 行程没验证就先订了不可退的机票
- `ignored_constraint` —— 一天 6 个景点，没算时间和体力
- `missing_success_criteria` —— 从没说清「什么算一趟好旅行」
- `dependency_or_sequencing_gap` —— 「临时购物」之后紧接着赶 10:00 的车
- `unaddressed_risk` —— 7 月去却没有雨天 / 高温的备选
- `unstated_assumption` —— 默认那家名怀石料理一定有位
- `no_fallback` —— 那家订不到就没有 plan B
- `goal_misalignment` —— 说是「放松」的旅行却从早排到半夜

`--profile fast` 跑一个评审，`standard` 跑全 3 个，`deep` 多轮直到没有**新**异议存活。

## 用法

**作为 skill，你不用记参数——直接问 agent。** 说「用 challenge-plans 审下这个计划」「这份 spec 能动手了吗」，甚至「challenge-plans 怎么用」——它会替你挑模式、挑命令，并把存活的异议带回来。

**想直接命令行跑？** 对照下表：

| 我想做… | 跑这条 |
|---|---|
| 看哪些后端就绪 | `challenge-plans doctor` |
| 审**任何计划** | `challenge-plans run trip.md --type plan --sink markdown` |
| 动手前审一份 **spec** | `challenge-plans run spec.md --type spec --sink markdown` |
| 审一次**代码改动** | `git diff > c.diff && challenge-plans run c.diff --type diff` |
| 审一个**已经做出的决定** | `challenge-plans run decision.md --type decision --sink markdown` |
| 在多个**还没定的**选项里**选** | `challenge-plans weigh options.yaml --sink markdown` |
| 让结论用**中文** | 加 `--lang zh` |
| 当 **CI gate** | 加 `--enforce`（`request_changes`/`inconclusive`/`schema_invalid` 退非零；`discuss`/`approve` 退 0） |

**`decision` / `plan` / `weigh` 怎么选？** 看它们落在一个选择的哪个阶段。`weigh` 在你**选之前**：≥2 个还没定的选项，帮你排序。`--type decision` 在你**选定一个之后**：压测这个已下的决定（漏了替代方案？证据撑得起赌注？回得了头？）。`--type plan` 是选定后**要走的步骤**：看它们能不能落地。同一趟旅行——`weigh` 选「飞还是高铁」，`decision` 审「我们决定飞」，`plan` 审逐日行程。

`--profile fast|standard|deep` 在速度和深度间取舍。`[sev✓]` = 跨家族已验证（可硬 gate）；`[sev?]` = 未验证、仅 advisory。可直接跑的样例在 [`examples/`](examples/)。未 pip 安装时前缀 `PYTHONPATH=src python3 -m challenge_plans.cli …`。

## 按你的语言输出

源码是英文，但评审可以用**任意**语言作答——加 `--lang`：

```bash
challenge-plans run plan.md --type plan --lang zh     # 结论用中文
challenge-plans weigh options.yaml --lang ja          # 议事用日语
```

它只切换人类可读的文字；JSON 键、枚举值、行锚保持原样，所以解析和 CI gate 都不受影响（等价于设 `CHALLENGE_PLANS_LANG`）。你的 agent 传 `--lang <用户语言>` 就能本地化整份评审。

## 工作原理

多个 persona/CLI challenger 先 steelman 再找漏洞；一条 high/critical 异议必须由**跨家族 Verifier** 用带行锚的证据复现，才能硬 gate；异议去重后收敛成一个**六态 verdict**——面板不完整绝不当作 `approve`。完整机制、两种模式、议事三段流程、7 个失败模式见 **[docs/how-it-works.md](docs/how-it-works.md)**。它也能和 [superpowers](https://github.com/obra/superpowers)、[grill-me](https://github.com/mattpocock/skills) 衔接——详见该文档。

## 后端

驱动你已登录的任一订阅编码 CLI —— **Claude Code**（`claude`）或 **OpenAI Codex**（`codex`），不绑定任何一家。两个不同厂商可互验；只有一个时结论保持 advisory。无 API key、不产生 per-token 费用。**至少要有一个**已登录的 CLI —— `challenge-plans doctor` 会列出每个后端状态和具体修复方式（去装、或登录）。

## 状态

**v1 — 可用。** 两模式端到端可跑，对真实 plan/spec 验证过、由 pytest 套件钉住不变量，经多轮跨 agent 对抗 review 加固（**包括这份 README 本身**）。已知边界见 [docs/how-it-works.md](docs/how-it-works.md)。

## 贡献

欢迎 issue / PR —— 见 [CONTRIBUTING.md](CONTRIBUTING.md)。本项目 dogfood：开 PR 前用 `challenge-plans run <change>.diff --type diff` 审一遍自己的改动。

## 许可

[Apache-2.0](LICENSE)。
