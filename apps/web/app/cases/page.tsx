import type { Metadata } from "next";
import Link from "next/link";

import { Plane } from "@/components/Plane";
import { Reveal } from "@/components/Reveal";

export const metadata: Metadata = {
  title: "演示记录 · SynapseMind 突触智学",
  description:
    "四段真实 transcript：数学错步、空白入口、物理弃权、语文结构提示。是链路记录，不是效果研究。",
};

interface Turn {
  ask: string;
  answer: string;
}

interface CaseStudy {
  id: string;
  no: string;
  subject: string;
  verdict: string;
  state: "card" | "scaffold" | "stop" | "hint";
  title: string;
  problem: string;
  student: string;
  turns: Turn[];
  notes: string[];
  outcome: string;
  boundary: string;
}

/*
 * 下面四段内容抄自 2026-10-31 22:35 的 walkthrough 实跑记录
 * （var/demo/walkthrough.md，本机生成、不入库）。只做了截断，没有改措辞；
 * 想核对原文就重跑一遍脚本。
 */
const CASES: CaseStudy[] = [
  {
    id: "math",
    no: "01",
    subject: "数学 · 标注题",
    verdict: "出卡：L2",
    state: "card",
    title: "写到了最后一行，但没有检查参数边界",
    problem:
      "已知函数 f(x)=ln x − a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。",
    student:
      "答案 a≥1/e。过程：「定义域 x>0。f′(x)=1/x−a，令 f′(x)=0 得 x=1/a。a>0 时最大值为 −ln a−1≤0，所以 a≥1/e。」",
    turns: [
      {
        ask: "a=0 时 f′(x)=1/x 在 x>0 上有零点吗？",
        answer: "A. 没有零点",
      },
      {
        ask: "a=0 这个边界情况需要单独检查吗？",
        answer: "A. 要，a=0 也在 a≤0 这一支里",
      },
    ],
    notes: [
      "单步验证：「1/x = 1/x + 1」—— fail；x=0.1 时左边 10、右边 11。",
      "显式退出：CLOSED；本次不生成卡点卡，也不展示最终答案（除非再显式请求一次）。",
    ],
    outcome:
      "卡点：条件转译 / 参数分类（L2，置信 0.84）。证据是「没有单独检查 a≤0 / a=0 的边界」「没有讨论 a≤0 时函数无上界」。下一步是 3 分钟的参数分类微课。",
    boundary: "标注题，图是人工准备的；这条记录证明卡面措辞与证据链能对上。",
  },
  {
    id: "blank",
    no: "02",
    subject: "数学 · 空白入口",
    verdict: "先示例，不提问",
    state: "scaffold",
    title: "完全没写：先给一步示例，再交回一行",
    problem:
      "已知函数 f(x)=ln x − a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。",
    student: "答案「不会」，过程留空。",
    turns: [
      {
        ask: "进入 SCAFFOLD：不选探针、不出卡，先给起步示例。",
        answer: "示例：确认定义域 x>0，并识别「对所有 x>0 成立」。",
      },
      {
        ask: "下一步提示",
        answer: "照着上面的写法，把你的下一行过程写出来；不用写最终答案。",
      },
      {
        ask: "学生写回一行后",
        answer: "回到 PROBE，开始正常追问；示例收起。",
      },
    ],
    notes: ["示例只读解法节点的文本，不读答案存储。"],
    outcome:
      "第一次空白得到示例，第二次空白会明确提示「先写一行再诊断」；这条记录只走到「写回一行 → 进入追问」。",
    boundary: "示例展示的是起步，不是本题答案；说它以偏概全会高估——它只覆盖第一格。",
  },
  {
    id: "physics",
    no: "03",
    subject: "物理 · 自动识别",
    verdict: "弃权：没有出卡",
    state: "stop",
    title: "五轮追问之后，系统没有凑一张卡",
    problem:
      "质量为 2 kg 的物块放在水平面上，受到与水平方向成 30° 的拉力 F=10 N，动摩擦因数 0.2，求物块的加速度。",
    student: "只写了「先读题，标出已知量。」没有声明学科。",
    turns: [
      {
        ask: "拉力方向与水平面成 30°，分解时先确定什么？",
        answer: "A. 水平与竖直分量",
      },
      {
        ask: "这道题里物块所受的滑动摩擦力大小应写成哪个式子？",
        answer: "A. μ(mg−Fsin30°)",
      },
      {
        ask: "要求物块的加速度，得先算出哪个量？",
        answer: "A. 支持力与摩擦力",
      },
    ],
    notes: ["直播实录里是 5 轮追问；这里只抄了 3 轮，省略号不是省略了正确答案。"],
    outcome:
      "五轮之后状态 CLOSED，没有卡点卡。transcript 如实写「没有出卡」，没有把低置信的猜测包装成诊断。",
    boundary:
      "这道题的图是实时生成的，没有人工复核；它证明链路能跑通，也证明系统会弃权，但不证明诊断准确。",
  },
  {
    id: "chinese",
    no: "04",
    subject: "语文 · NONE 档",
    verdict: "只给结构提示",
    state: "hint",
    title: "没有客观真值的题，只按结构自查",
    problem: "阅读下面的文字，完成题目：文中两次写到「灯」，请结合全文简要分析其作用。",
    student: "答案「不会」，过程留空；没有声明学科。",
    turns: [
      {
        ask: "识别为语文，进入 NONE 档",
        answer: "不追问、不定位卡点，只按线索词与分句重合给结构提示。",
      },
      {
        ask: "结构提示",
        answer:
          "这道题拆成 8 步；你的过程里看起来没有写到「读题干，圈出“两次”“灯”“结合全文”“作用”及分值」。",
      },
      {
        ask: "下一步",
        answer:
          "先补上「读题干，圈出“两次”“灯”“结合全文”“作用”及分值」这一步，再回来按结构自查。",
      },
    ],
    notes: [
      "固定免责声明：该学科没有可自动验证的标准答案；这里只判断「这一步有没有被写到」，不判断写得对不对，也不定位卡点。",
    ],
    outcome: "状态 CLOSED；只给结构提示，没有卡点卡。",
    boundary: "结构提示不是诊断；它只说「你没写到哪一步」，不说「你哪里想错了」。",
  },
];

export default function CasesPage() {
  return (
    <div className="sm-about sm-cases">
      <section className="sm-about-hero">
        <Plane>
          <p className="sm-eyebrow">
            <span aria-hidden="true" className="sm-dot" />
            演示记录 · 四段 transcript
          </p>

          <h1 className="sm-display">
            四段记录，
            <span className="sm-display-2">四种收束。</span>
          </h1>

          <p className="sm-lede">
            下面四段来自同一次实跑（2026-10-31 22:35，本机）：数学错步出卡、空白入口给示例、
            物理五轮后弃权、语文只给结构提示。文字按 transcript 抄录，只做截断。
          </p>

          <p className="sm-fine">
            这是链路记录，不是效果研究。没有对照组，没有准确率，也没有 24 小时后的延迟正确率。
          </p>
        </Plane>
      </section>

      <Reveal className="sm-flow sm-flow--narrow">
        <Plane>
          <h2 className="sm-label">
            <em>01</em>
            四段记录
          </h2>

          <p className="sm-statement">每段都标了它不能证明什么。</p>

          <ol className="sm-case-list">
            {CASES.map((item) => (
              <li className="sm-tile sm-case" data-state={item.state} key={item.id}>
                <header className="sm-case-head">
                  <span className="sm-case-no">{item.no}</span>
                  <span className="sm-case-subject">{item.subject}</span>
                  <span className="sm-case-verdict">{item.verdict}</span>
                </header>

                <h3 className="sm-case-title">{item.title}</h3>

                <dl className="sm-case-rows">
                  <div>
                    <dt>题目</dt>
                    <dd>{item.problem}</dd>
                  </div>
                  <div>
                    <dt>学生写了</dt>
                    <dd>{item.student}</dd>
                  </div>
                </dl>

                <ol className="sm-case-turns">
                  {item.turns.map((turn) => (
                    <li key={turn.ask}>
                      <p className="sm-case-ask">{turn.ask}</p>
                      <p className="sm-case-answer">{turn.answer}</p>
                    </li>
                  ))}
                </ol>

                {item.notes.length > 0 ? (
                  <ul className="sm-case-notes">
                    {item.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                ) : null}

                <p className="sm-case-outcome">{item.outcome}</p>

                <p className="sm-case-boundary">
                  <b>不能证明</b>
                  {item.boundary}
                </p>
              </li>
            ))}
          </ol>
        </Plane>
      </Reveal>

      <Reveal className="sm-flow sm-flow--center">
        <Plane>
          <h2 className="sm-label">
            <em>02</em>
            复跑与边界
          </h2>

          <p className="sm-statement">能复算的记录，才配叫演示。</p>

          <div className="sm-about-split">
            <div className="sm-tile sm-about-card">
              <b>怎么复跑</b>
              <p>
                <code>python scripts/demo/walkthrough.py</code> 走四段并写{" "}
                <code>var/demo/walkthrough.md</code>；<code>--no-live</code> 只跑标注题与空白，
                物理 / 语文显式跳过；<code>--case physics</code> 可单跑一段。
              </p>
            </div>

            <div className="sm-tile sm-about-card sm-about-card--quiet">
              <b>重跑会变吗</b>
              <p>
                数学与空白走规则路径，记录稳定；物理与语文依赖实时建图，换模型或断网会变。
                变的是链路，不是准确率。
              </p>
            </div>
          </div>

          <p className="sm-fine">
            这些记录能证明四件事：三个入口都在、证据不足时会停、示例不含答案、结构提示不冒充诊断。
            不能证明「说得准」——那需要真实学生作答与双人标注，目前还没有。
          </p>

          <p className="sm-about-oath">
            演示样例，不是效果研究；不放准确率，不放编造的百分比。
          </p>

          <p className="sm-about-back">
            <Link href="/science">五条机制与引用 →</Link>
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