# 文档总索引

> 目录怎么划分见 [STRUCTURE.md](../STRUCTURE.md)；进度、未决项、环境陷阱见 [AGENTS.md](../AGENTS.md)。
> 这份文件只回答一件事：**想了解某件事该读哪一份，以及那一份现在还算不算数。**

## 一、先分清自己在读哪一层

| 层 | 入口 | 回答的问题 | 时效 |
|---|---|---|---|
| **设想层** | [vision/learning-mechanism.md](vision/learning-mechanism.md) | 这套东西凭什么可能有用：诊断 → 归因 → 干预 → 巩固 | **不过期**（设想不随实现变） |
| **主体层** | [../README.md](../README.md) → 本目录 [design/chapters/](design/chapters/) | 它到底怎么工作：认知动作空间、状态机、解法图、契约 | 随设计改；改了就同步 `specs/` |
| **实现层** | [adr/](adr/README.md) → `chapters/12`、`13` → [../AGENTS.md](../AGENTS.md) | 现在做到哪、为什么这么选、踩过什么坑 | **每轮都变**，只信 AGENTS 里写的日期 |

一句话记法：**README 讲架构不讲进度；AGENTS 讲进度不讲架构；设想不承诺已实现。**

## 二、目录职责

| 目录 | 放什么 | 入库 | 什么时候该改 |
|---|---|---|---|
| [`adr/`](adr/README.md) | 决策记录：背景、选项、评分、后果、**改选条件** | ✅ | 做技术选型时新增一篇；旧篇只补「后来怎样」，不改写当时理由 |
| [`design/chapters/`](design/chapters/) | 公开设计章节：00–05、07、12–15（一页纸、需求、核心体验、科学原理、诊断引擎、Prompt、技术架构、交付/插件/视觉/附录） | ✅ | 设计变了改这里，**不要改 DOCX/PDF** |
| `design/release/` | 合并稿 MD、DOCX、PDF、`openapi.json` | ❌ 生成物 | 改了章节后重建（见第五节） |
| [`design/assets/`](design/assets/) | 3 张设计图，由本地文档工具生成 | ✅ | 图变了重跑本地脚本，不要手改 PNG |
| [`vision/`](vision/) | 设想层：学习机理、CHC 归因、生物类比与文献 | ✅ | 只增不删；与实现冲突时**以实现为准** |
| `design/plan/` | 本地详尽计划、未入库的取舍记录 | ❌ 本机 | 只在本地会话里用 |

## 三、按身份选路径

- **只想看这是什么东西（10 分钟）**：[00 一页纸](design/chapters/00-一页纸.md) → [02 核心体验](design/chapters/02-核心体验.md) → [设想层](vision/learning-mechanism.md)
- **接手开发（2 小时）**：[AGENTS.md](../AGENTS.md) 全文 → [`specs/dialogue-state.md`](../specs/dialogue-state.md) → [ADR-0001](adr/0001-language-and-code-architecture.md) → [12 章 M2 交付计划](design/chapters/12-M2交付计划.md) → [13 章 学科插件](design/chapters/13-学科插件与可扩展架构.md)
- **只改前端**：[14 章 视觉系统](design/chapters/14-视觉系统.md) ＋ `apps/web/`
- **只改诊断**：[04 章 诊断引擎](design/chapters/04-诊断引擎.md) ＋ [`specs/solution-graph.schema.json`](../specs/solution-graph.schema.json)
- **想知道“准不准”**：[eval/README.md](../eval/README.md)（公开评测协议与汇总；逐题报告留在本地）

## 四、阅读顺序（按依赖，不按编号）

1. [00 一页纸](design/chapters/00-一页纸.md)
2. [01 需求与场景](design/chapters/01-需求与场景.md)
3. [02 核心体验](design/chapters/02-核心体验.md)
4. [03 科学原理与对话规则](design/chapters/03-科学原理与对话规则.md)
5. [04 诊断引擎](design/chapters/04-诊断引擎.md)
6. [05 Prompt 与 Agent](design/chapters/05-Prompt与Agent.md)
7. [07 技术架构](design/chapters/07-技术架构.md)
8. [ADR-0001 语言与代码架构](adr/0001-language-and-code-architecture.md)（技术选型先看这篇）
9. [12 M2 交付计划](design/chapters/12-M2交付计划.md) → [13 学科插件与可扩展架构](design/chapters/13-学科插件与可扩展架构.md)
10. [14 视觉系统](design/chapters/14-视觉系统.md) → [15 附录](design/chapters/15-附录.md)

> 按需读：15 附录（术语、JSON 示例与参考方向）。

## 五、构建设计书（本地）

`design/chapters/` 是唯一手写源。DOCX/PDF 的构建脚本与产物属于本地文档工作流，不随公开仓库发布；需要重建时在私有工作区运行，生成物写到已忽略的 `design/release/`，不要直接改中间稿或 DOCX。
