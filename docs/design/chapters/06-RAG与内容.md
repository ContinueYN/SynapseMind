## 6. RAG 与内容：让追问有据可查

### 6.1 知识库不是“教材切片”，是五类卡片

| 类型 | 内容 | 典型字段 | 用途 |
|---|---|---|---|
| `concept` | 概念卡：定义、适用条件、反例 | `concept_id`, `grade`, `prereq` | 解释“为什么” |
| `graph` | 题目解法图 | `problem_id`, `nodes`, `edges` | 对齐与定位 |
| `error` | 错因卡：L0–L6 + 典型信号 | `error_id`, `layer`, `signals` | 生成假设 |
| `hint` | 提示卡：0–3 级，逐级上升 | `hint_id`, `level`, `target_node` | 降级支架 |
| `transfer` | 迁移题：同结构/变式 | `item_id`, `root_node`, `answer_hash` | 24h/7d 验证 |

**关键设计**：chunk 不是固定 500 字，而是**一张卡 = 一个语义单元**。这样检索结果可以直接作为“提示”，而不是一段需要再总结的教材。

### 6.2 文档 ETL

```text
PDF/图片/网页
  → Tika/PaddleOCR
  → 结构识别（标题/公式/表格）
  → LaTeX 归一化
  → 人工校对（关键题）
  → 卡片化（concept/graph/error/hint）
  → bge-m3 向量化
  → PostgreSQL + pgvector
```

数学公式处理：

- `ln x`、`\ln x`、`log_e x` 统一为 `ln(x)`；
- 区间 `[1/e,+∞)` 统一为 `Interval(1/e, oo)`；
- 用 SymPy 做等价校验，避免“看起来一样、其实不同”。

### 6.3 切分策略

| 内容 | 切分 | 原因 |
|---|---|---|
| 概念卡 | 按“定义/条件/反例/常见误用”四段 | 追问时只取需要的一段 |
| 解法图 | 按节点，不切边 | 保留依赖关系 |
| 错因卡 | 一卡一因 | 假设空间要可枚举 |
| 提示卡 | 按 level 切 | 0–3 级逐级调用 |
| 教材 | 按小节 + 公式块 | 保留上下文 |

每块 200–480 token，重叠 60–80 token；解法图节点不切。

### 6.4 检索：混合召回 + 重排

一次追问的 query 不是“题目原文”，而是：

```text
题目：ln x - a x ≤ 0 恒成立
学生步骤：令 f'(x)=0 得 x=1/a
候选假设：漏参数分类 / 概念不清
目标：找“驻点存在性”的概念卡 + 反例提示
```

检索流程：

1. **查询增强**：把题目、学生步骤、候选假设拼成 query；必要时 HyDE 生成“假设性解释”，但只在诊断阶段用，不直接展示。
2. **混合召回**：BM25 top 40 + dense top 40。
3. **RRF 融合**：`score = Σ 1/(60+rank_i)`。
4. **重排**：bge-reranker top 50 → 8。
5. **硬过滤**：`acl_level`、`chunk_type != solution`、年级/学科匹配。
6. **阈值**：低于 0.35 不强行引用，改为“通用提示”。

### 6.5 pgvector 配置

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE kb_chunk (
  id            BIGSERIAL PRIMARY KEY,
  chunk_type    TEXT NOT NULL,          -- concept/error/hint/graph
  title         TEXT NOT NULL,
  content       TEXT NOT NULL,
  metadata      JSONB NOT NULL,
  embedding     vector(1024) NOT NULL,
  acl_level     SMALLINT NOT NULL DEFAULT 1,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_kb_chunk_hnsw
  ON kb_chunk USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);

CREATE INDEX idx_kb_chunk_type ON kb_chunk (chunk_type);
```

查询时设置 `SET LOCAL hnsw.ef_search = 80;`，在召回率与延迟之间取平衡。

### 6.6 内容生产：100 题，30 题深标

MVP 不追求“全题库”，追求“可诊断的密度”。

| 层级 | 数量 | 标注内容 | 用途 |
|---|---|---|---|
| **种子题** | 100 | 题目、答案、解法图骨架、知识点 | 覆盖高频题型 |
| **深标题** | 30 | 每个节点的 `demand`、`common_errors`、`probe_templates` | 支撑高质量诊断 |
| **金标准对话** | 100 条 | 学生步骤 + 教师卡点 + 好/坏追问 | 评测 |
| **迁移题** | 60 | 每个深标题 2 道同构/变式 | 24h/7d 验证 |

标注流程：

1. 一位教研写解法图；
2. 第二位教研独立标卡点与探针；
3. 不一致的题进入“争议集”，第三人裁决；
4. 只有双人一致的题，才允许进入“高置信”诊断。

**质量门槛**：30 道深标题的节点一致率 ≥0.80，探针一致率 ≥0.75；达不到就缩范围，不硬上。

### 6.7 提示卡：0–3 级，不许跳级

| 级别 | 形式 | 例子 |
|---|---|---|
| 0 | 元认知提示 | “你先说说，你写到这一步时在算什么？” |
| 1 | 方向提示 | “先别求最大值，先看 a≤0 时有没有最大值。” |
| 2 | 具体提示 | “a=-1 时，f'(x)=1/x+1，它有零点吗？” |
| 3 | 半成品 | “f'(x)=1/x-a。当 a>0 时，令 f'(x)=0，得 x=____。” |

规则：用户说“不知道”一次，降一级；连续两次，给半成品；不允许从 0 直接跳到 3。

### 6.8 引用与可追溯

每条提示/解释都带：

- `source_id`：概念卡/教材页码；
- `source_version`：内容版本；
- `why`：为什么召回它（对应哪个假设/节点）。

诊断卡里的“为什么不是计算错误”，必须能链到一条 `error` 卡和一条用户证据。没有来源的“我觉得”，不允许进入诊断。

### 6.9 内容侧的 SEO/GEO

这不是主产品，但能自然体现 skill.txt 第 7 项：

- 公开页 `/q/{problem_id}/breakpoints`：这道题的 3 个常见卡点（不展示完整答案）；
- 概念页 `/concept/{slug}`：定义、适用条件、反例、1 道自测；
- 结构化数据：`LearningResource` + `FAQPage`；
- `llms.txt` + sitemap 分片；
- 监测 AI 搜索引用：答案前置、事实密度、来源日期。

公开页的作用不是“引流”，而是让教研内容被检索、被引用、被纠错，反哺诊断库。