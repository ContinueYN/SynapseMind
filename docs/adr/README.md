# 架构决策记录

这里记录影响架构、接口或运维成本的决策。每份 ADR 对应一个问题，写明选项、取舍、后果与改选条件。

## 索引

| 编号 | 决策 | 状态 |
|---|---|---|
| [0001](0001-language-and-code-architecture.md) | 语言与代码架构 | accepted |
| [0002](0002-llm-provider-and-golden-scale.md) | 模型供应商与金标准规模 | accepted |
| [0003](0003-generated-graph-evidence-calibration.md) | 生成图的证据权重校准 | accepted |
| [0004](0004-first-question-latency-budget.md) | 首问 8s 预算下的生成题延迟治理 | accepted |

## 写法

```text
# ADR-000N: 标题
- 状态：proposed / accepted / superseded
- 日期：
- 决策者：
- 相关：

## 背景
## 约束
## 选项
## 决策
## 后果
## 验证
```

决策以可验证的约束为依据；没有验证方式的“最优”不构成决策理由。