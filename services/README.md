# services

**现在不建。** 这里留给 MVP 之后按触发条件拆出的独立服务。

## 为什么不提前拆

3 个人 8 周，拆 7 个进程会带来：Nacos 配置、Feign 契约、分布式事务、链路排查、联调排队。当前阶段用一个模块化单体 + 明确包边界，收益更大。

## 拆分触发条件

满足任意两条再拆：

- 单个模块的发布频率 > 2 次/周，且与其他模块互相阻塞；
- AI 调用与业务事务的资源画像差异 > 3 倍（CPU/内存/超时/扩缩）；
- 故障域需要隔离（AI 挂了，诊断卡仍可出）；
- 团队 > 6 人，包边界已经出现跨组合并冲突；
- 单表/单库写入达到分片阈值，且缓存无法吸收。

## 目标服务

`gateway`、`session`、`problem`、`diagnosis`、`knowledge`、`evidence`、`ai-orchestrator`。

拆分时每个服务必须有：独立数据库 schema、契约测试、SLO、回滚脚本。没有这四样，不拆。

## 目录约定

```text
services/
├─ session/
├─ problem/
├─ diagnosis/
├─ knowledge/
├─ evidence/
└─ ai-orchestrator/
```

> 当前为空。代码先落在 `apps/api` 的对应包。**目录先不创建，避免“看起来拆了、实际没拆”。**