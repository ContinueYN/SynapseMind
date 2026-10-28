# apps/api

Java 21 + Spring Boot 3 的**模块化单体**。先跑 4 个部署单元，服务边界在包与接口上，不提前拆进程。

## 计划模块

```text
com.synapsemind
├─ gateway        # 鉴权、限流、SSE 透传
├─ session        # 会话状态机、锁、幂等
├─ problem        # 题目、OCR 结果、解法图
├─ diagnosis      # 步骤对齐、假设、探针、卡点卡
├─ knowledge      # 五类知识卡、检索编排
├─ evidence       # 证据、迁移验证、复核队列
├─ ai             # Prompt 组装、模型路由、输出校验
└─ shared         # 错误码、事件、DTO、可观测性
```

## 里程碑

| 阶段 | 交付 | 退出条件 |
|---|---|---|
| M1 | `session` + `problem` + `diagnosis` 的文本闭环 | 3 道题端到端可演示 |
| M2 | `ai` 追问 + JSON Schema 校验 + 降级 | 5 轮内区分 2 个假设 |
| M3 | `knowledge` 检索 + 引用 | recall@8 ≥0.80 |
| M4 | `evidence` 迁移验证 + 教师复核 | 24h 迁移可记录 |

## 约定

- Controller 不写业务；Service 不拼 Prompt；Prompt 只在 `ai/prompt`。
- 所有 LLM 输出先过 JSON Schema，再进状态机。
- 学习模式响应 DTO 里**不允许出现 `solution` 字段**。
- 数据库变更用 Flyway；接口变更先改 `specs/`，再改代码。

## 构建（目标）

```bash
./mvnw -q -DskipTests package
./mvnw spring-boot:run
```

> 当前目录只有设计说明，尚未提交 `pom.xml` 与源码。