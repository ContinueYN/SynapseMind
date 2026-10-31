import type { Metadata } from "next";
import Link from "next/link";

import { Plane } from "@/components/Plane";
import { Reveal } from "@/components/Reveal";

export const metadata: Metadata = {
  title: "科学依据 · SynapseMind 突触智学",
  description:
    "五条设计机制、它们各自映射到哪个产品动作，以及每一条都不声称什么。引用是概念来源，不是疗效证据。",
};

interface Reference {
  authors: string;
  title: string;
  source: string;
  doi: string;
}

interface Mechanism {
  key: string;
  tag: string;
  name: string;
  mechanism: string;
  maps: string;
  boundary: string;
  refs: Reference[];
}

const MECHANISMS: Mechanism[] = [
  {
    key: "plasticity",
    tag: "机制 01",
    name: "突触可塑性 / LTP",
    mechanism:
      "一次成功提取，会让同一条通路下一次更容易被调用；久不用的连接会变弱。",
    maps: "卡点卡把探针答对记为支持假设的证据，把答错记为排除；「下次先练什么」写在卡面最后一行。",
    boundary:
      "我们把它当作更新规则的形状：成功则强化、失败则打折。不测量大脑活动，也不声称用户身上发生了 LTP。",
    refs: [
      {
        authors: "Citri, A., & Malenka, R. C. (2008).",
        title: "Synaptic plasticity: Multiple forms, functions, and mechanisms.",
        source: "Neuropsychopharmacology, 33(1), 18–41.",
        doi: "10.1038/sj.npp.1301559",
      },
      {
        authors: "Kandel, E. R. (2001).",
        title:
          "The molecular biology of memory storage: A dialogue between genes and synapses.",
        source: "Science, 294(5544), 1030–1038.",
        doi: "10.1126/science.1067020",
      },
    ],
  },
  {
    key: "retrieval",
    tag: "机制 02",
    name: "提取练习（testing effect）",
    mechanism:
      "先试着回忆，比再读一遍更能留下长期记忆，即使当下感觉更费劲、更容易出错。",
    maps: "系统先问不先讲：前 3 轮不出现最终答案，一次只问一个问题，选项不超过 4 个。",
    boundary:
      "这条机制解释「为什么先问」，不证明我们的追问本身有效；我们没有做对照实验。",
    refs: [
      {
        authors: "Roediger, H. L., & Karpicke, J. D. (2006).",
        title:
          "Test-enhanced learning: Taking memory tests improves long-term retention.",
        source: "Psychological Science, 17(3), 249–255.",
        doi: "10.1111/j.1467-9280.2006.01693.x",
      },
      {
        authors: "Karpicke, J. D., & Blunt, J. R. (2011).",
        title:
          "Retrieval practice produces more learning than elaborative studying with concept mapping.",
        source: "Science, 331(6018), 772–775.",
        doi: "10.1126/science.1199327",
      },
    ],
  },
  {
    key: "spacing",
    tag: "机制 03",
    name: "间隔与遗忘",
    mechanism: "把同样的练习分散到不同时间，比一次练很久保持得更久。",
    maps: "卡点卡给出复习到期间隔 due_hours；当前是固定的 24 小时代理量，还没有按通路强度排期。",
    boundary:
      "没有真实的延迟正确率，due_hours 不是记忆测量。这一条目前只落到「有一个字段」，没有落到排期算法。",
    refs: [
      {
        authors: "Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T., & Rohrer, D. (2006).",
        title: "Distributed practice in verbal recall tasks: A review and quantitative synthesis.",
        source: "Psychological Bulletin, 132(3), 354–380.",
        doi: "10.1037/0033-2909.132.3.354",
      },
      {
        authors: "Dunlosky, J., Rawson, K. A., Marsh, E. J., Nathan, M. J., & Willingham, D. T. (2013).",
        title: "Improving students' learning with effective learning techniques.",
        source: "Psychological Science in the Public Interest, 14(1), 4–58.",
        doi: "10.1177/1529100612453266",
      },
    ],
  },
  {
    key: "load",
    tag: "机制 04",
    name: "认知负荷与示例效应",
    mechanism:
      "对刚开始学的人，先看一个完整的示例，比直接解题更省工作记忆；示例要围住当下这一个动作。",
    maps: "完全没写时进入 SCAFFOLD：先给 1–2 步起步示例，提交一行后回到追问；示例只读解法节点文本，不含最终答案。",
    boundary:
      "示例只示范起步，不替学生走完；也没有做示例渐隐的对照实验。",
    refs: [
      {
        authors: "Sweller, J. (1988).",
        title:
          "Cognitive load during problem solving: Effects on learning.",
        source: "Cognitive Science, 12(2), 257–285.",
        doi: "10.1207/s15516709cog1202_4",
      },
      {
        authors: "Sweller, J., & Cooper, G. A. (1985).",
        title:
          "The use of worked examples as a substitute for problem solving in learning algebra.",
        source: "Cognition and Instruction, 2(1), 59–89.",
        doi: "10.1207/s1532690xci0201_3",
      },
    ],
  },
  {
    key: "metacognition",
    tag: "机制 05",
    name: "元认知与 CHC 标签空间",
    mechanism:
      "人对自己会不会的判断经常失准；能力适合分类描述，不适合压成一个分数。",
    maps: "卡面只说「本题的认知需求」；打开 CHC 开关时，也只显示 focus 节点需求最高的两维，并沿用固定措辞「单题不足以断言」。",
    boundary:
      "不输出 IQ、百分位或能力分，不把七维写成学生画像。单题不足以断言任何一项能力。",
    refs: [
      {
        authors: "Carroll, J. B. (1993).",
        title:
          "Human Cognitive Abilities: A Survey of Factor-Analytic Studies.",
        source: "Cambridge University Press.",
        doi: "10.1017/CBO9780511571312",
      },
      {
        authors: "Bjork, R. A., Dunlosky, J., & Kornell, N. (2013).",
        title: "Self-regulated learning: Beliefs, techniques, and illusions.",
        source: "Annual Review of Psychology, 64(1), 417–444.",
        doi: "10.1146/annurev-psych-113011-143823",
      },
    ],
  },
];

export default function SciencePage() {
  return (
    <div className="sm-about sm-science">
      <section className="sm-about-hero">
        <Plane>
          <p className="sm-eyebrow">
            <span aria-hidden="true" className="sm-dot" />
            科学依据 · 五条机制
          </p>

          <h1 className="sm-display">
            借的是机制，
            <span className="sm-display-2">不借疗效。</span>
          </h1>

          <p className="sm-lede">
            这一页只回答一个问题：每个设计决定是从哪条研究结论借来的，以及借到哪为止。
            每条机制都写三行——机制本身、它对应的产品动作、我们不声称的部分。
          </p>

          <p className="sm-fine">
            引用是设计概念的来源，不是效果证据。我们没有做对照实验，没有延迟正确率，也不测量大脑。
          </p>
        </Plane>
      </section>

      <Reveal className="sm-flow sm-flow--narrow">
        <Plane>
          <h2 className="sm-label">
            <em>01</em>
            五条机制
          </h2>

          <p className="sm-statement">每条机制都带一行「不声称」。</p>

          <ol className="sm-science-list">
            {MECHANISMS.map((mechanism) => (
              <li className="sm-tile sm-mech" key={mechanism.key}>
                <header className="sm-mech-head">
                  <span className="sm-mech-tag">{mechanism.tag}</span>
                  <b>{mechanism.name}</b>
                </header>

                <p className="sm-mech-line">
                  <span className="sm-mech-k">机制</span>
                  {mechanism.mechanism}
                </p>

                <p className="sm-mech-line">
                  <span className="sm-mech-k">产品动作</span>
                  {mechanism.maps}
                </p>

                <p className="sm-mech-line sm-mech-line--quiet">
                  <span className="sm-mech-k">不声称</span>
                  {mechanism.boundary}
                </p>

                <ul className="sm-mech-refs">
                  {mechanism.refs.map((reference) => (
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
                </ul>
              </li>
            ))}
          </ol>
        </Plane>
      </Reveal>

      <Reveal className="sm-flow sm-flow--center">
        <Plane>
          <h2 className="sm-label">
            <em>02</em>
            共同边界
          </h2>

          <p className="sm-statement">机制能解释设计，不能替产品担保。</p>

          <div className="sm-about-split">
            <div className="sm-tile sm-about-card">
              <b>这些引用支持什么</b>
              <p>
                支持这些形状：先提取再讲解、分散练习、用示例降低起步负荷、把能力当分类而不是分数。
                它们各自有实验证据，我们借的是结论的方向。
              </p>
            </div>

            <div className="sm-tile sm-about-card sm-about-card--quiet">
              <b>这些引用不支持什么</b>
              <p>
                不支持「用 SynapseMind 会提分」。我们还没有同一批学生的对照数据，
                没有 24 小时后的延迟正确率，也没有把类比写成神经测量。
              </p>
            </div>
          </div>

          <p className="sm-about-oath">
            不承诺提分；不输出 IQ、百分位、能力分；不把类比写成神经测量；不把演示 transcript 当效果研究。
          </p>

          <p className="sm-about-back">
            <Link href="/cases">看四段真实 transcript →</Link>
            <span aria-hidden="true"> · </span>
            <Link href="/about">为什么这样设计 →</Link>
            <span aria-hidden="true"> · </span>
            <Link href="/">← 回到交题</Link>
          </p>
        </Plane>
      </Reveal>
    </div>
  );
}