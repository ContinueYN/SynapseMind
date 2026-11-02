# specs

**契约先于代码。** 这里的文件是运行时 JSON、状态机与数据结构的单一来源；`apps/` 的实现必须与它们一致。

| 文件 | 用途 | 消费者 |
|---|---|---|
| [`problem-input.schema.json`](problem-input.schema.json) | 交题入口 | Web、API |
| [`solution-graph.schema.json`](solution-graph.schema.json) | 题目解法图 | API（生成物运行时严格校验）、内容后台 |
| [`problem-graph.schema.json`](problem-graph.schema.json) | 通用问题图（目标/约束/选项/风险/下一步，v0.1） | API（生成物运行时严格校验）、Web、评测 |
| [`generic-review.schema.json`](generic-review.schema.json) | 通用产物：结构复盘/决策框/复现卡共用外壳（v0.1） | API、Web、评测 |
| [`diagnosis.schema.json`](diagnosis.schema.json) | 卡点卡输出（v0.1；`SYNAPSE_CHC_ATTRIBUTION=on` 时 v0.2 追加可选 `card.attribution`） | API、Web、评测 |
| [`structure-hint.schema.json`](structure-hint.schema.json) | 结构提示输出（NONE 档学科） | API、Web、评测 |
| [`step-verification.schema.json`](step-verification.schema.json) | 单步验证输出（`POST /sessions/{id}/steps`） | API、Web |
| [`code-execution.schema.json`](code-execution.schema.json) | 显式代码执行输出（`POST /executions`，v0.1） | API、评测 |
| [`agent-trace.schema.json`](agent-trace.schema.json) | 有界只读工具轨迹 + 结构复盘（`GET /sessions/{id}/agent`，v0.2） | API、Web、评测 |
| [`agent-run.schema.json`](agent-run.schema.json) | 显式代码复现请求（`POST /sessions/{id}/agent/run`，v0.1） | API、Web |
| [`review-queue.schema.json`](review-queue.schema.json) | 异议复核只读列表（`GET /review/items`） | API、Web |
| [`knowledge-search.schema.json`](knowledge-search.schema.json) | 只读知识卡检索（`GET /knowledge/search`） | API、Web |
| [`dialogue-state.md`](dialogue-state.md) | 追问状态机与事件 | API、AI 编排、评测 |

## 约定

1. 先改 spec，再改代码；破坏性变更升 `version`。
2. JSON 使用 UTF-8、`snake_case`、时间为 ISO 8601 UTC。
3. 学习模式的响应中**不允许有 `solution` 字段**；这是硬约束，不是建议。唯一的例外是用户显式 `POST /sessions/{id}/exit` 且 body 为 `{"reveal": true}`：此时才读 `AnswerStore`，标注题返回答案与完整解法，生成题只返回「没有存储解法」。
4. `confidence < 0.55` 时只能输出“可能卡点”，不能下确定结论。
5. 所有 `id` 用稳定字符串，不用自增整数做外部契约。

## 校验

`specs/*.json` 必须能被标准 JSON 解析器读取；CI 不再做仓库级文档完整性检查。运行时校验以 `solution-graph.schema.json` 和 `structure-hint.schema.json` 为准。

解法图生成物是例外：`infrastructure/llm/graph.py` 在运行时用 `jsonschema` 直接加载本目录的 `solution-graph.schema.json` 做严格校验（M2.5 S4）。契约只有这一份，代码不另抄一套字段。

`problem-input.schema.json` 是交题入口（v0.2，Phase 0）。`problem.subject` 从三值枚举改为**开放标签**（1–32 字符）：省略时由系统识别，识别不出或置信不足进入 `GenericProfile` 通用模式，不再返回 422；显式写一个系统不认识的标签也照样接受，并保留原文作为标签。领域只是标签，真正决定“能说多硬的话”的是验证方式（FORMAL / EXECUTABLE / EMPIRICAL / ARGUMENTATIVE）。`SessionOut` 相应新增 `domain`（`name`/`label`/`verification`/`generic`/`confidence`）与可选 `intake`；`intake` 是入口整理，不是卡点卡：不含层级、把握、诊断结论或答案。`intake` **v0.2** 增加 `observed`（学生自己那段话里被认出的结构项）与 `gaps`（该验证方式要求、但那段话里没提到的项，最多 3 条）；两者都只说明“有没有写到/提到”，不判断对错，也不给出选项排序，没有作答时都为空。

`problem-graph.schema.json` 是通用问题图契约（Phase 1b，v0.1）。它和解法图不是同一张图：解法图描述“解题步骤”，通用图描述问题本身的目标、已知、约束、假设、计划、尝试、证据、检查、选项、风险与下一步。节点只记录“提到了什么”，不记录对错；`source=student` 表示从学生原话原样复制，`source=system` 表示模型整理，来源决定界面如何标注，不决定内容可信。`g1` 是 Phase 1a 的线索抽取，`g2` 是生成图；只有 `g2` 可以带 `formal`/`empirical`。`formal` 复用 `solution-graph.schema.json#/$defs/claim`，只把**学生已经写出的答案**形式化，不替学生解题；`empirical` 只接受结构化方程/表达式、单位与数值，没有结构化输入就不从自然语言猜单位。两者都是可选字段：没有声明、验证器没运行、或输入无法解析时结果为 `unknown`，不假装检查过。

`SessionOut.intake` 升 **v0.3**：除 v0.2 的 `observed`/`gaps` 外，新增 `origin`（`student`/`system`/`null`）、`graph`（最多 12 个 `kind`/`label`/`text`/`source` 节点）与 `verifications`（`formal`/`empirical` 各至多一条，含 `status` 与可读 `detail`）。`graph` 是结构整理，不是卡点结论；`verifications` 只有在对应 claim 存在且验证器实际运行时才可能是 `pass`/`fail`，否则必须是 `unknown`。决策问题仍然只列选项、约束、代价与可逆实验，从不排序或推荐。

入口的澄清问题**最多问一次、最多收一次**：`POST /api/v1/sessions/{id}/intake` 接受 `{"answer": "..."}`，把这段补充并入 `initial_answer` 后重新派生 `observed`/`gaps`，并让 `clarifier` 变成 `null`。如果补充明确点名“决策/代码/数学/物理/写作/科研/工作”中的一类，服务端会把该会话的**展示领域**切到对应标签（`SessionOut.domain` 与 `intake.domain` 一起变，内部 `subject` 仍是提交时的插件键），`domain_confidence` 记为 0.8；它只换清单和检索标签，仍然没有验证。它不推进状态、不生成卡点卡、不给答案；会话仍是 `CLOSED`。第二次补充不会被追加，返回 200 且 `notice` 说明「只接受一次」；没有待补充问题的入口（包括高置信领域和已有卡点卡的会话）返回 **409**，空串或超过 500 字返回 **422**。

`intake` 再升 **v0.4**：新增可选 `probe`（`kind`/`question`/`answered`/`limit`），它是**结构补充**，不是诊断探针。一次只显示一个缺口问题，最多接受 3 次；`POST /api/v1/sessions/{id}/intake/probe` 接受 `{"answer": "..."}`，把补充并入 `initial_answer` 后重新派生 `observed`/`gaps`，再把 `probe` 换成下一个缺口或 `null`。领域澄清问题优先：它还没回答时 `probe` 为 `null`，答完后才会出现结构补充。没有待补充缺口、澄清问题未答或次数用完时返回 **409**，空串或超过 500 字返回 **422**。这段补充不推进入口状态、不出卡、不给答案，也不会重新判定领域或判断对错；会话仍是 `CLOSED`。

`intake` 再升 **v0.5**：新增可选 `review`，形状即 [`generic-review.schema.json`](generic-review.schema.json) v0.1。它只在有作答、且验证方式为 `ARGUMENTATIVE`（写作/科研/决策/通用）时派生：`kind=structure` 是结构复盘（headline/findings/evidence/not_checked/next_step/disclaimer），`kind=decision` 另给按学生写到顺序排列的 `options`（每个含代价、风险与可逆实验）与 `tradeoff_question`，不排序、不推荐；`kind=execution` 留给 T4。`formal`/`empirical`/`executable` 不生成 review；组合失败时 `review=null` 并保留 v0.4 的全部字段，入口不返回 500。review 每次读取时派生，不进会话快照、不读 `AnswerStore`、不推进状态，也不是卡点卡。

`solution-graph.schema.json` 的 `probe.evidence` 是可选字段：生成图必须为每个选项给出 log-odds 权重（结构规则强制），手写种子图可省略并从 `EVIDENCE` 取权重；字段形状在 schema 里约束，跨字段一致性（选项覆盖、targets 对应、每个 target 至少被使用一次）在 `domain/problem/graph_structure.py` 里校验（M2.5 S5）。**键是选项字母**（`A`/`B`/`C`…，与 `SubmitAnswerCommand.option_id` 同一套编码），不是选项文本——`HypothesisSet.observe()` 按字母查表，写错键名不报错，只是那次作答不更新后验。

`structure-hint.schema.json` 是 NONE 档学科（语文/英语/历史）的唯一输出契约（M2.5 S7，v0.2 起为 S8）。它不是卡点卡的简化版，而是**另一种承诺**：`steps[].status`（`covered`/`partial`/`missing`）只描述“解法图里的这一步有没有被写到、是否只写到一部分”，由存在性对齐（线索词 + 分句重合）得出，不代表写得对错；`focus_node_id` 是“下一步先看哪里”（第一个没有完全写到的节点），不是卡点；`disclaimer` 必须写明该学科没有可自动验证的真值。NONE 档不进入 `PROBE`，也不生成卡点卡——`application/commitment.py` 是这条承诺的唯一开关。v0.2 只新增 `partial` 与 `version` 变化；`partial` 不是“写错”，也不改变卡点卡路径。

`review-queue.schema.json` 是内部复核页的只读列表契约（v0.1）。它只暴露卡片的 `layer`/`label`/`node_id`/`one_line`/`confidence` 与来源会话、时间，**不含学生原文**；`GET /api/v1/review/items` 只读，不写回复核库，也不推进任何会话。人工判断（准确 / 说得通但不对 / 空泛）由复核者在浏览器里标记并导出 CSV，不进入服务端契约。

`knowledge-search.schema.json` 是本地知识卡检索的只读契约（v0.2）。`GET /api/v1/knowledge/search` 只接受概念标签（`q`）、**开放领域标签**过滤（`subject`，1–40 字符，不是白名单）和可选的验证方式过滤（`verification`：`formal` / `executable` / `empirical` / `argumentative`），**不接受学生作答原文**；返回 `card_id`、五类 `kind`（concept/pattern/method/error/source）、`subject`、`verifications`、标题、摘录、出处（title/url/license）与余弦分数。`enabled=false` 表示 `SYNAPSE_RAG` 未开启，此时 `hits` 为空，客户端隐藏面板。检索不推进会话、不修改卡点卡、不写库；没有模型时 API 返回 503 并带安装提示，而不是静默返回空结果。

`agent-trace.schema.json` 是通用入口的有界工具轨迹契约（Phase 4，v0.2）。`GET /api/v1/sessions/{id}/agent` 只对**没有参考结构的入口会话**可用；已有解法图/卡点卡的会话返回 **409**，不会为了展示轨迹去跑第二套诊断。轨迹最多 **3 步**，v0.2 仍只有确定性规则选择，不调模型；`steps[].tool` 限定为 `check_structure` / `search_patterns` / `search_sources` / `compare_options` / `ask_clarifying` / `run_code` / `run_tests`，没有 `get_answer`、`set_state` 或推进会话的工具。写作/研究会优先查 `source` 类卡；没有来源卡就写 `skipped`，不会把概念卡包装成来源。`status` 只表示**工具调用**的状态（`ok`/`skipped`/`failed`），不是学生答案或代码的对错结论；复查失败、RAG 未开启、执行开关关闭都必须如实写 `failed`/`skipped`，不能补一个通过。轨迹只记录输入/输出摘要和知识卡引用，不记录学生原文或思维链；`suggestions` 只给结构、来源、可逆实验或澄清问题，不排序选项，也不给唯一答案。v0.2 增加 `reflection`（`focus`/`next`/`boundary`）：只复述结构缺口与工具状态，不是卡点结论，也不替用户做选择。

`agent-run.schema.json` 是显式代码复现请求（v0.1）。`POST /api/v1/sessions/{id}/agent/run` 只接受调用方粘贴的 Python `code` 与可选 `tests`，**不从题面或会话自动抽代码**；只有 `EXECUTABLE` 框架接受代码，`tests` 必须与 `code` 一起提交。它与 `/executions` 共用同一个受限本地执行器和 `SYNAPSE_EXEC` 开关：关闭时轨迹里是 `skipped`（“没有运行”），不是 `pass`；执行结果只进入轨迹摘要和可逆实验建议，不写会话、不读答案库、不生成卡点卡。`pass` 仍只表示退出码 0 或提交的测试通过，不表示代码正确。

`code-execution.schema.json` 是显式代码执行的响应契约（Phase 2，v0.1）。`POST /api/v1/executions` 只接受调用方明确提交的 Python 代码与可选 unittest 文件，不读会话、不写会话、不选代码、不调模型；默认 `SYNAPSE_EXEC=off`，关闭时返回 **403**，不伪造一次运行。开启后仍有墙钟上限、内存/单进程限制、输出上限与静态闸门（导入白名单、禁止 `eval`/`exec`/`open`/进程/网络入口）；这是本地受限执行，不是容器级安全沙箱，不能用来运行恶意代码。`pass` 只表示退出码为 0 或提交的测试通过，不表示代码正确、覆盖完整或通过了隐藏测试；`timeout` 和 `rejected` 的 `exit_code` 必须为 `null`，`rejected` 至少带一条 finding。

`step-verification.schema.json` 是「交一步」的响应契约（M2.5 S5 ⑥，v0.2）。`POST /api/v1/sessions/{id}/steps` 只把这一条步骤交给会话所属学科的 `SubjectPlugin.verify()`，**不推进状态、不生成卡点卡、不返回答案**。`fail` 必须带学生自己写的式子或两边数值（例如 `x→0 时左边极限 0.5、右边 2`）；v0.2 起同时给出结构化 `findings`（`kind`/`left`/`right`/`summary`，必填、最多 3 条），`detail` 仍保留为一句可读说明，前端不必解析它来拆公式；schema 的 `if/then` 约束 `fail` 至少 1 条、`unknown`/`pass` 为空。`unknown` 表示开关未开、式子读不懂、没发现可机器证明的错误，或该学科没有可判的真值——`unknown` 不是“这步对了”，它的 `findings` 必须为空。数学的等式链校验由 `SYNAPSE_EQUALITY_CHECK` 控制，默认 `off`。

图顶层的 `claim` 也是可选字段（M2.5 S5），把答案写成机器可证伪的形式：

```json
"claim": {
  "kind": "parameter_range",
  "parameter": "a",
  "variable": "x",
  "variable_domain": "(0,+inf)",
  "constraint": {"expression": "log(x) - a*x", "relation": "<="},
  "answer": [{"lower": "1/E", "upper": null, "lower_inclusive": true, "upper_inclusive": false}]
}
```

含义是 `∀x∈variable_domain: expression <relation> 0 ⇔ parameter ∈ answer`；`answer` 的端点是 SymPy 表达式字符串，`null` 表示无穷，多个区间即并集。v1 只支持这一种形状（参数区间）；求一个值、解集、证明题没有 `claim`，验证结果为 `unknown`，不算失败。`kind`/`relation` 不在支持范围内时，结构规则会丢弃 claim 并记一条修复（`claim_dropped_unsupported`），图仍然可用。校验与反例由 `infrastructure/verification/` 执行（`pass|fail|unknown`）：`fail` 会带着具体反例让建图器**只重写区间**（`graph_claim_repair`，表达式/参数/定义域钉死），仍失败则丢弃 claim（`claim_dropped_refuted`）、保留图，反例留在 `GraphBuildResult.verification` 里。
