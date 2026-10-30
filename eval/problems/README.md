# eval/problems

M2.5 题集。JSONL 一行一题。

| 文件 | 内容 |
|---|---|
| `unseen-v0.2.jsonl` | **100 道高中数学题**，每题带 `expected_answer`；建图、首问、复盘都跑它 |
| `unseen-v0.1.jsonl` | 最早的 20 道，保留作对照（历史报告的样本口径） |
| `physics-v0.1.jsonl` | 6 道物理题，只验「同一状态机 + 物理插件」的链路 |
| `chinese-v0.1.jsonl` | 6 道语文题，NONE 档结构提示 |
| `student-answers-v0.1.jsonl` | 学生作答样本（`work` + `answer` + 期望卡点），真实复盘用；目前 3 条 `synthetic` |
| `student-answers-template.csv` | 上面这个文件的可填模板（含表头 + 3 行示例），老师/自己录数据用 |
| `public-attempts-v0.1.jsonl` | **4 道公开题**：题目来自公开问答页，配的是学生自己写的原话（不是我们出的题） |
| `student-answers-pub-v0.1.jsonl` | 上面 4 道题的学生作答，`source=public-web` 且带 `source_url` |

> `eval/` 整体在 `.gitignore` 内。本目录的文件需要 `git add -f`，否则新克隆与 CI 都没有题。

## 为什么有 `expected_answer`

v0.1 只有题干：它能回答「图建出来没有」，回答不了「卡点对不对」。v0.2 给每题补了最终答案，于是复盘可以分开两件事：

- **建图/出卡**：图合法、卡点节点属于这张图（自动可测）；
- **诊断准确率**：卡点是否落在老师会指的那一步（需要人判，`expected_answer` 只用来判断学生答对没有）。

题目本身不参与 prompt 调参：系统性失败只修通用规则，并在报告里记 prompt 版本。

## 字段

| 字段 | 说明 |
|---|---|
| `id` | 题目 id，必须匹配 `^P_[A-Z0-9_]+$`（图契约要求） |
| `subject` / `grade` | 学科与学段；数学 `math`，物理 `physics`，语文 `chinese` |
| `topic` | 主题标签，进报告，方便看哪类题失败 |
| `text` | 题干原文；学生提交的题面应大致等于它 |
| `expected_answer` | 规范答案，仅供复盘判断「学生答对没有」；**不进 prompt、不进图** |

`student-answers-v0.1.jsonl` 的字段（也接受同名 CSV：`--answers xxx.csv`，带表头的列名与下表一致，示例见 `student-answers-template.csv`）：

| 字段 | 说明 |
|---|---|
| `problem_id` | 对应题集里的 `id` |
| `student_id` | 匿名编号，不要写真实姓名 |
| `answer` / `work` | 学生的最终答案与过程原文（原样，不要润色、不要把错的地方改对） |
| `expected_bottleneck` | 老师认为的卡点关键字（如「导数符号」），复盘时与卡点节点做去空白的子串匹配 |
| `final_correct` | 最终答案是否正确（`是/否`、`true/false` 都认）；用来区分「答错且卡点吻合」与「答对却被指卡点」 |
| `source` | `student`（同一批学生的真实复盘）、`public-web`（公开问答页里学生自己写的过程，带 `source_url`，只能小样本粗检）、`synthetic`（只验管线，不能算准确率） |
| `source_url` | 可选；`public-web` 必填，记原帖地址，报告末尾会列出来 |

### 从公开问答页收数据（不必等老师）

公开问答页（如作业帮的提问页）里，学生常把自己的推导写出来再问「我哪里错了」。这类帖子可以整条搬过来当小题集：**题干来自帖子、`work` 是学生原话**，不需要把别人的答案硬套到我们的 100 题上。

1. 搜「我算的是…答案是…错在哪」这类句式，挑**带自己推导**的帖子（只报答案的没用）。
2. `public-attempts-v0.1.jsonl` 每题一行：`id` 用 `P_PUB_00x`，`text` 按原题整理，`expected_answer` 用老师解析的结论。
3. 作答行写进 `student-answers-pub-v0.1.jsonl`：`work` 摘学生原话（可截断，但**不要改写他的算式**），`source` 写 `public-web`，`source_url` 记原帖。
4. `expected_bottleneck` 尽量用学生自己说的困惑或老师指出的那一步，别用自己臆测的；拿不准就留空（报告显示 `—`，不计入命中率）。
5. 跑法同下，只是换 `--problems` / `--answers`。

> 合规与边界：只摘与卡点相关的几句话、标明出处，仅内部评测用；这不是同一批题、同一批学生的抽样，结论只能说「在这 4 条上」。

### 收真实作答的操作口径

1. 先收 **5–10 条**（足够跑通复盘、看出管线问题），每个学生 1–2 题；要算准确率再扩到 20–50 条。
2. 每题只抄三样：**学生的原话过程**、**他写的最终答案**、**你认为的卡点**（可以只写 2–4 个字的关键词，比如「导数符号」「没求高」）。
3. 过程要原样，**不要替他补步骤、不要把错的改对**——对齐器就是靠「他到底写没写」来判断的。
4. 用 CSV 最省事：复制 `student-answers-template.csv`，删掉示例行，按列填；`source` 写 `student`。
5. 放回 `eval/problems/` 后跑：

```powershell
cd apps/api
$env:SYNAPSE_LLM_MODE='on'
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_review.py --answers ..\..\eval\problems\student-answers-v0.1.csv
```

## 运行

数学建图（100 题，约 8–10 分钟；需真实 key）：

```powershell
cd apps/api
.\.venv\Scripts\python.exe ..\..\scripts\eval\s4_graph_build.py --problems ..\..\eval\problems\unseen-v0.2.jsonl
```

首问门禁与请求链路同理，都接受 `--problems`。

真实学生作答复盘：

```powershell
cd apps/api
$env:SYNAPSE_LLM_MODE='on'
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_review.py --limit 5
```

产出 `eval/reports/m2.5-s5-student-review.md`：逐条列出出卡结果、卡点层、卡面一句、期望卡点是否命中，最后一列 `人工判断` 留空给老师填（准确 / 说得通但不对 / 空泛）。**填完这一列才有诊断准确率**；在那之前只有出卡率与命中率两个代理指标。

公开学生原话那 4 条（`--problems public-attempts-v0.1.jsonl --answers student-answers-pub-v0.1.jsonl`）产出 `eval/reports/m2.5-s5-student-review-pub.md`。

## 命名

版本号进文件名，不覆盖旧版本：`unseen-v0.2.jsonl` → `unseen-v0.3.jsonl`。