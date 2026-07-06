# challenge-plans（中文）

[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue.svg)]()
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/hiadrianchen/challenge-plans/ci.yml?branch=main)](https://github.com/hiadrianchen/challenge-plans/actions)

> English: [README.md](README.md)

**执行计划前先过一遍：用你已登录的 AI 编程 CLI（Claude Code、Codex 等）做一轮对抗式交叉评审，无需 API Key。**

`challenge-plans` 会编排你本机上的订阅制 CLI（Claude Code、Codex……）对一份计划交叉拷问，提前挖出会导致返工的坑——再把**经得起推敲、最终存活**的异议汇聚成一份裁决（verdict）。它可以当 CLI、当 **Agent Skill**、当 CI 门禁用，并嵌入 superpowers 的计划生命周期：`writing-plans → challenge-plans → executing-plans`。

## 为什么用 challenge-plans

- 🔑 **不用 API Key，不按量计费** —— 直接调用你已登录的订阅制 CLI（Claude Code、Codex），有一个就能跑。
- 🧪 **证据胜过人数** —— 哪怕只有一方提异议，只要带可复现的反证，就能压过多数票；对错不由投票决定。
- 🤝 **跨模型家族验证** —— 一条异议必须被**另一个独立的模型家族**用带行号锚点的证据复现，才拿得到硬门禁（hard gate）资格（`✓`）；单个模型的说法只算参考（advisory）。
- 🛡️ **内置 7 种多 Agent 失效模式的防护** —— 选票丢失、选项锚定、半途甩锅、多数压少数、单轮就收、虚假共识、伪收敛（[详见原理](docs/how-it-works.md)）。
- 🌍 **按你的语言输出** —— 加 `--lang zh`（或 `ja`、`de`……），评审结论就用目标语言输出；一个参数切换，不必另维护翻译版本。

## 它能做什么

不写规格文档（spec）也能用。它有两种模式——**审**（`run`）一份你已经写好的东西，或在几个选项间**选**（`weigh`）。两种模式都会把内容交给**不同模型家族**的 AI 交叉拷问，只留下「有证据、且被另一个模型复核过」的意见，而不是单个模型拍脑袋。

**审**（`run`）能审四类：

- 📋 **任何计划**（`--type plan`）—— 旅行、上线、招聘、搬家都能审。比如一份京都行程：Day2 塞了六个景点、还现在就订了不可退的机票——它会指出哪天根本跑不完、哪步回不了头。
- 📝 **一份成型的规格 / 设计稿**（`--type spec`）—— 动手前先过一遍。比如「异步导出用户 CSV」：怎样算导出成功？谁来验收？漏了哪条边界？省得你照着含糊的规格做出错的东西。
- 🔧 **一次代码改动**（`--type diff`）—— 轻量代码评审。把 `git diff` 丢进去，它会盯住你改了函数却没跟着改的调用点、没补的测试、悄悄破掉的兼容性。
- 🧭 **一个你已经做出的决定**（`--type decision`）—— 技术选型、选供应商、招人都行。比如「我们决定把项目重写成 TS」：更便宜的替代方案（先把环境清干净）你公平比过吗？理由是不是沉没成本？这步回得了头吗？

**选**（`weigh`）是另一种模式：在几个**还没定**的选项间拿不准时用——技术选型也好，生活里的选择也好。比如在 Postgres / MongoDB / SQLite 之间选、或在三个 offer 里挑一个：它让多个 AI 投票排序，但给每个模型家族的票数封顶（免得一个聒噪的模型制造虚假共识），并把最有力的反对意见摆上台面——给你一份带「为什么」和「谁不同意」的排序，而不是一句武断的答案。

## 快速开始

**最省事——交给你的 Agent。** 对它说：

> 从 https://github.com/hiadrianchen/challenge-plans 安装 challenge-plans，然后运行 `challenge-plans doctor`。

它会装好包，并报告哪些后端已就绪。

**或者手动安装**（Python ≥ 3.10）：

```bash
pip install challenge-plans      # 或：pipx install challenge-plans  ·  uvx challenge-plans doctor
challenge-plans doctor           # 看哪些 CLI 已登录

# 已经装过了？按当初的装法用对应一句命令更新：
#   pip install -U challenge-plans   ·   pipx upgrade challenge-plans
#   uvx 跑的是缓存版本——要最新版用 `uvx challenge-plans@latest …`（或加 `--refresh`）
```

至少要有一个已登录的 CLI —— **Claude Code**（`claude`）或 **OpenAI Codex**（`codex`）；同时登录两家不同厂商即可开启跨模型家族验证。**作为 Agent Skill 使用时**：把 [SKILL.md](SKILL.md) 放进你的 Agent 能发现技能的目录即可。（要改源码？`git clone … && pip install -e .`。）

## 看它跑

下面把「**任何计划**」这一类（四种之一）用在一份粗糙的京都旅行攻略上（[`examples/plan-sample.md`](examples/plan-sample.md)）：

```text
$ challenge-plans run examples/plan-sample.md --type plan --sink markdown

# challenge-plans · challenge · verdict: request_changes
- [high✓] 机票不可退，却在行程通过验证前就锁死        @L10  (irreversibility_or_high_cost, by claude:feasibility)
- [med ] Day2 横跨全城塞了 6 个景点，基本走不完        @L4   (ignored_constraint, by gpt:risk)
- [med ] 从没定义「什么算一趟好旅行」，无从判断好坏     @L1   (missing_success_criteria, by claude:goal-alignment)
```

每一行都是一条**带标签的异议**——锚定到具体行号，由某个只盯一件事的评审视角（persona）提出。上面三条分别来自三个视角：

- **可行性** *（现实里能不能落地？）* → 抓到**机票不可退**、却在行程通过验证前就锁死。
- **风险** *（哪里最可能出错 / 不可逆？）* → 抓到 **Day2 横跨全城塞了 6 个景点**、完全没留时间余量。
- **目标对齐** *（这些步骤能达成目标吗？）* → 抓到**从没定义「什么算一趟好旅行」**，于是无从判断。

每条异议都从一份固定的「**计划失效模式**」清单里选标签——这让每条都具体、好去重。这趟旅行里，各个标签分别抓到了：

- `irreversibility_or_high_cost`（不可逆 / 高成本） —— 行程没验证就先订了不可退的机票
- `ignored_constraint`（无视约束） —— 一天 6 个景点，没算时间和体力
- `missing_success_criteria`（缺成功标准） —— 从没说清「什么算一趟好旅行」
- `dependency_or_sequencing_gap`（依赖 / 时序漏洞） —— 「临时购物」之后紧接着赶 10:00 的车
- `unaddressed_risk`（未处理风险） —— 7 月出行却没有雨天 / 高温的备选
- `unstated_assumption`（未言明的假设） —— 默认那家著名怀石料理一定有位
- `no_fallback`（无降级方案） —— 那家订不到就没有 Plan B
- `goal_misalignment`（目标错位） —— 说是「放松」的旅行，日程却从早排到半夜

`--profile fast` 只跑一个评审视角，`standard` 跑全部 3 个，`deep` 则多轮评审，直到没有**新**异议再冒出来（收敛）。

## 用法

**作为 Agent Skill 使用时，你不用记参数——直接吩咐 Agent。** 说「用 challenge-plans 审下这个计划」「这份规格能动手了吗」，甚至「challenge-plans 怎么用」——它会替你选模式、选命令，并把最终存活的异议带回来。

**想直接在命令行跑？** 对照下表：

| 我想… | 运行 |
|---|---|
| 看哪些后端就绪 | `challenge-plans doctor` |
| 审**任何计划** | `challenge-plans run trip.md --type plan --sink markdown` |
| 动手前审一份**规格** | `challenge-plans run spec.md --type spec --sink markdown` |
| 审一次**代码改动** | `git diff > c.diff && challenge-plans run c.diff --type diff` |
| 审一个**已经做出的决定** | `challenge-plans run decision.md --type decision --sink markdown` |
| 在多个**还没定的**选项里**选** | `challenge-plans weigh options.yaml --sink markdown` |
| 让结论用**中文** | 加 `--lang zh` |
| 当 **CI 门禁** | 加 `--enforce`（`request_changes`/`inconclusive`/`schema_invalid` 退非零；`discuss`/`approve` 退 0） |

**`decision` / `plan` / `weigh` 怎么选？** 看它们落在一个选择的哪个阶段。`weigh` 在你**选之前**：面对 ≥2 个还没定的选项，帮你排序。`--type decision` 在你**已经选定之后**：压测这个已下的决定（漏了替代方案？证据撑得起赌注？回得了头？）。`--type plan` 则是选定后**要走的步骤**：看它们在现实里能不能落地。还是同一趟旅行——`weigh` 选「坐飞机还是坐高铁」，`decision` 审「我们决定坐飞机」这个选择，`plan` 审逐日行程。

`--profile fast|standard|deep` 在速度和深度之间取舍。`[sev✓]` = 已跨模型家族验证（可设硬门禁）；`[sev?]` = 未验证、仅作参考。可直接运行的样例在 [`examples/`](examples/)。未用 pip 安装时，在命令前加 `PYTHONPATH=src python3 -m challenge_plans.cli …`。

## 按你的语言输出

源码与默认输出是英文，但评审可以用**任意**语言作答——加 `--lang` 即可：

```bash
challenge-plans run plan.md --type plan --lang zh     # 结论用中文
challenge-plans weigh options.yaml --lang ja          # 议事分析用日语
```

它只切换人类可读的文字；JSON 键名、枚举值、行号锚点都保持原样，所以解析和 CI 门禁判定都不受影响（等价于设置环境变量 `CHALLENGE_PLANS_LANG`）。你的 Agent 传入 `--lang <用户语言>`，就能把整份评审本地化。

## 工作原理

多个代表不同评审视角的挑战者会先**充分肯定其合理之处**（steelman），再去找漏洞；一条 high/critical 级别的异议，必须由**跨模型家族的验证者（Verifier）**用带行号锚点的证据独立复现，才能升级为硬门禁；异议去重后收敛成一个**六态裁决**——评审团不完整时，绝不轻易判 `approve`。

**为什么是一个工具，而不是一段提示词 / skill.md / MCP？** 因为难的不是"让模型对抗式地审一遍"——难的是它周围那些**属于控制流、写不进提示词**的保证：得让**另一家厂商**的模型复现之后才算数（不是同一个模型自己判自己）；裁决是**用代码**从存活证据里算出来的，不是模型说了算；回复被截断/超时会被抓出来、而不是静默当作"没问题"；而且它骑你的订阅、不按 token 计费。一句话——**提示词负责产出证据，Python 负责产出裁决。** 逐个脚本干嘛、为什么这么做（9 个模块地图）、两种模式、议事流程、7 种失效模式，全在 **[docs/how-it-works.md](docs/how-it-works.md)**。它也能与 [superpowers](https://github.com/obra/superpowers)、[grill-me](https://github.com/mattpocock/skills) 衔接——详见该文档。

## 后端 —— 你需要准备什么

调用你已登录的任一订阅制编码 CLI —— **Claude Code**（`claude`）或 **OpenAI Codex**（`codex`），通过它们的无头模式运行，用你现有的订阅额度。不用 API Key，也不会按 token 计费。**至少要有一个**已登录的 CLI 才能跑；`challenge-plans doctor` 会列出每个后端的状态和具体修复方式（去装、或登录）。

能拿到多少，取决于你登录了几家**不同厂商**：

| 你登录了几家 | 实际跑什么 | 局限 |
|---|---|---|
| **一家**（Claude *或* Codex） | 多个评审视角从不同角度、基于你这一个订阅轮番挑刺——已经比「只问模型一次」强得多。 | 结论只能是**参考**（advisory）：模型发现的问题**都不能设硬门禁**，裁决最高到 `discuss`（即便没发现问题也到不了 `approve`），并附一个 `low_diversity` 警告。跨模型家族的 `[sev✓]` 确认**关闭**。但 `--verify`（跑测试 / lint）的机械失败**仍能硬门禁**——那是客观证据，不靠模型投票。 |
| **两家**（Claude *和* Codex） | 以上全部，**外加**跨模型家族的验证者：一条 high/critical 异议必须被**另一家厂商的模型**用带行号锚点的证据独立复现，才有硬门禁资格。 | 这才是核心亮点——`[sev✓]` 确认、真正的 `request_changes` / `approve` 裁决。 |

所以单一订阅下，它是一份「加强版的单模型评审」；**要让一条发现具备能硬门禁的跨家族验证，需要接入第二家、不同厂商的后端。**

## 状态

**v1 — 可用。** 两种模式都已端到端跑通，经真实计划 / 规格验证，由 pytest 套件锁定行为不变量，并经过多轮跨 Agent 对抗式评审加固（**包括这份 README 本身**）。已知的边界限制见 [docs/how-it-works.md](docs/how-it-works.md)。

## 贡献

欢迎提交 issue 和 PR —— 见 [CONTRIBUTING.md](CONTRIBUTING.md)。本项目践行「自己先用」（dogfood）：提交 PR 前，先用 `challenge-plans run <change>.diff --type diff` 评审一遍自己的改动。

## 许可

[Apache-2.0](LICENSE)。
