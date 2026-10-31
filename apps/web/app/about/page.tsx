import type { Metadata } from "next";
import Link from "next/link";

import { Plane } from "@/components/Plane";
import { Reveal } from "@/components/Reveal";

export const metadata: Metadata = {
  title: "为什么这样设计 · SynapseMind 突触智学",
  description:
    "突触是类比，CHC 是标签空间。这里写清楚我们验证了什么、还没有验证什么。",
};

const CHECKS = [
  {
    question: "步骤有没有被写到",
    state: "done",
    label: "已有",
    method: "存在性对齐 · 构造真值",
    note: "写了的步骤被认出 59/98；缺口被认成 missing 13/19。只判有没有写，不判对错。",
  },
  {
    question: "一个等号成不成立",
    state: "done",
    label: "已有",
    method: "SymPy 反例",
    note: "能给出具体反例；没找到反例不等于整步正确。",
  },
  {
    question: "图拆得对不对",
    state: "partial",
    label: "待验证",
    method: "结构全过，人工样本小",
    note: "100 道题结构合法；另 20 题人工抽查 19/20。结构合法不等于拆对，也不是诊断准确率。",
  },
  {
    question: "卡点归因对不对",
    state: "partial",
    label: "待验证",
    method: "只有构造真值",
    note: "缺口探针能测召回；还没有同一批题的真实学生作答。",
  },
  {
    question: "24 小时后还记不记得",
    state: "todo",
    label: "未做",
    method: "没有延迟正确率",
    note: "复习卡与间隔排期还没做，所以不承诺「学会了」。",
  },
] as const;

const REFERENCES = [
  {
    authors: "Carroll, J. B. (1993).",
    title: "Human Cognitive Abilities: A Survey of Factor-Analytic Studies.",
    source: "Cambridge University Press.",
    doi: "10.1017/CBO9780511571312",
  },
  {
    authors: "Sweller, J. (1988).",
    title: "Cognitive load during problem solving: Effects on learning.",
    source: "Cognitive Science, 12(2), 257–285.",
    doi: "10.1207/s15516709cog1202_4",
  },
  {
    authors: "Hattie, J., & Timperley, H. (2007).",
    title: "The power of feedback.",
    source: "Review of Educational Research, 77(1), 81–112.",
    doi: "10.3102/003465430298487",
  },
  {
    authors: "Kandel, E. R. (2001).",
    title:
      "The molecular biology of memory storage: A dialogue between genes and synapses.",
    source: "Science, 294(5544), 1030–1038.",
    doi: "10.1126/science.1067020",
  },
  {
    authors: "Citri, A., & Malenka, R. C. (2008).",
    title: "Synaptic plasticity: Multiple forms, functions, and mechanisms.",
    source: "Neuropsychopharmacology, 33(1), 18–41.",
    doi: "10.1038/sj.npp.1301559",
  },
] as const;

export default function AboutPage() {
  return (
    <div className="sm-about">
      <section className="sm-about-hero">
        <Plane>
          <p className="sm-eyebrow">
            <span aria-hidden="true" className="sm-dot" />
            设计说明 · 不是效果声明
          </p>

          <h1 className="sm-display">
            突触是类比，
            <span className="sm-display-2">不是脑扫描。</span>
          </h1>

          <p className="sm-lede">
            SynapseMind 用一张解法图定位你卡住的那一步。这里解释这个名字、图上的能力标注，
            以及我们还没有做到哪里。
          </p>

          <p className="sm-fine">
            我们不展示脑成像，不写没有出处的百分比，也不承诺提分。这一页只交代设计依据与边界。
          </p>
        </Plane>
      </section>

      <Reveal className="sm-flow sm-flow--narrow">
        <Plane>
          <h2 className="sm-label">
            <em>01</em>
            为什么叫突触
          </h2>

          <p className="sm-statement">把「学会」写成一条会被强化的通路。</p>

          <div className="sm-about-split">
            <div className="sm-tile sm-about-card">
              <b>借用的</b>
              <p>
                我们把它写成：一次成功提取，比再听一遍更能让一条解法通路变稳；失败不是清零，是打折。
                这两条更新规则给了「练一次强一点、久不用会掉」一个可计算的形状。
              </p>
            </div>

            <div className="sm-tile sm-about-card sm-about-card--quiet">
              <b>不声称的</b>
              <p>
                不测量大脑活动，不把「突触」写成已经发生的神经变化。
                它只是一个让模型能写下来的类比，不是神经读数。
              </p>
            </div>
          </div>

          <p className="sm-fine">
            类比只约束模型形状：成功提取后增强、久不用衰减。它不能反过来证明我们改变了你的大脑。
          </p>
        </Plane>
      </Reveal>

      <Reveal className="sm-flow sm-flow--right">
        <Plane>
          <h2 className="sm-label">
            <em>02</em>
            CHC 放在哪
          </h2>

          <p className="sm-statement">七维是标签，不是分数。</p>

          <p className="sm-p">
            CHC（Cattell–Horn–Carroll）是一套能力分类学。我们借它的词汇，把「这一步需要什么」
            写清楚：读懂条件、转译条件、同时抓住几个限制、检查是否用到了前提。
          </p>

          <div className="sm-about-terms">
            <span className="sm-chip sm-about-term">读懂条件</span>
            <span className="sm-chip sm-about-term">转译条件</span>
            <span className="sm-chip sm-about-term">同时抓住几个限制</span>
            <span className="sm-chip sm-about-term">检查前提</span>
          </div>

          <p className="sm-fine">
            当前版本里，这套标注默认关闭；打开 `SYNAPSE_CHC_ATTRIBUTION` 后，卡面只显示本题 focus 节点需求最高的两维，措辞是「题目需求标签，不是能力测评」。它仍不更新后验，也没有用来选探针。
            我们不输出 IQ、百分位或「能力分」；单题也不足以断言任何一项能力。
          </p>
        </Plane>
      </Reveal>

      <Reveal className="sm-flow sm-flow--center">
        <Plane>
          <h2 className="sm-label">
            <em>03</em>
            验证到哪一步
          </h2>

          <p className="sm-statement">能机判的，和还不能机判的，分开写。</p>

          <div className="sm-about-checks">
            {CHECKS.map((check) => (
              <article className="sm-tile sm-about-check" key={check.question}>
                <header>
                  <b>{check.question}</b>
                  <span className="sm-about-state" data-state={check.state}>
                    {check.label}
                  </span>
                </header>
                <p>{check.method}</p>
                <small>{check.note}</small>
              </article>
            ))}
          </div>

          <p className="sm-fine">
            前两项有可复现的验收；第三、四项只有小样本或构造真值；第五项没有数据。这张表是产品边界，不是路线图承诺。
          </p>
        </Plane>
      </Reveal>

      <Reveal className="sm-flow sm-flow--narrow">
        <Plane>
          <h2 className="sm-label">
            <em>04</em>
            参考
          </h2>

          <p className="sm-statement">设计概念的来源，不是效果背书。</p>

          <ol className="sm-about-refs">
            {REFERENCES.map((reference) => (
              <li key={reference.doi}>
                <span>{reference.authors}</span>{" "}
                <cite>{reference.title}</cite>{" "}
                <span>{reference.source}</span>{" "}
                <a
                  href={`https://doi.org/${reference.doi}`}
                  rel="noreferrer"
                  target="_blank"
                >
                  doi:{reference.doi}
                </a>
              </li>
            ))}
          </ol>

          <p className="sm-fine">
            这些文献是能力分类、认知负荷、反馈机制与突触可塑性的来源。它们不是对本产品效果的背书：
            我们没有做对照实验，也没有延迟正确率；神经科学只借「成功提取会强化通路」的形状，不是脑测量。
          </p>

          <p className="sm-about-oath">
            不输出 IQ、百分位、能力分；不承诺提分；不把类比写成神经测量。
          </p>

          <p className="sm-about-back">
            <Link href="/">← 回到交题</Link>
          </p>
        </Plane>
      </Reveal>
    </div>
  );
}