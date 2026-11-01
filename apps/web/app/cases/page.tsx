import type { Metadata } from "next";
import Link from "next/link";

import { Plane } from "@/components/Plane";
import { Reveal } from "@/components/Reveal";

export const metadata: Metadata = {
  title: "演示记录 · SynapseMind 突触智学",
  description:
    "六段实跑记录：数学错步、空白入口、物理弃权、语文结构提示，以及通用入口的决策与代码问题。是链路记录，不是效果研究。",
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
  state: "card" | "scaffold" | "stop" | "hint" | "intake";
  title: string;
  problem: string;
  student: string;
  turns: Turn[];
  notes: string[];
  outcome: string;
  boundary: string;
}

/*
 * 前四段抄自 2026-10-31 22:35 的 walkthrough 实跑记录，第五段是 2026-11-01
 * 新增的通用入口实跑（离线规则路径），第六段是同日的代码问题实跑
 * （显式提交，SYNAPSE_EXEC=off）。都来自 var/demo/walkthrough.md
 * （本机生成、不入库）。只做了截断，没有改措辞；想核对原文就重跑一遍脚本。
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
  {
    id: "decision",
    no: "05",
    subject: "生活决策 · 通用入口",
    verdict: "只给结构问题",
    state: "intake",
    title: "选项摆出来了，系统仍不替你排序",
    problem:
      "要不要换工作：现在的工作稳定但学不到东西；新机会钱多一点，但要搬到另一个城市，女朋友在这边。",
    student:
      "目标是两年内能持续学东西。要么留在现在的工作，稳定、离家近，但学不到新东西；要么接受新机会，钱多一点，但要搬到另一个城市，女朋友还在这边。约束是不能异地，半年内要决定。",
    turns: [
      {
        ask: "入口先问（一次只问一个）",
        answer: "每个选项会失去什么？",
      },
      {
        ask: "学生补上代价",
        answer:
          "留在原地的代价是继续学不到东西；换的代价是要异地、重新租房。",
      },
      {
        ask: "工具轨迹（v0.3，规则模式）",
        answer:
          "check_structure ok：看到 4 项结构、缺口 1 个；compare_options ok：2 个选项、1 条约束、1 条代价，只并列不排序；ask_clarifying ok：kind=next，answered=1/3。",
      },
    ],
    notes: [
      "规划器 `off/planner_off`：没有 key，中间一步仍由规则选；轨迹仍是 3 步。",
      "线索表只认「要么 / 还是 / 或者」这类连接词；换成「现在的工作 / 新机会」可能数不出两个选项。",
    ],
    outcome:
      "状态 CLOSED；没有卡点卡。补上代价后，只剩「可逆实验」一个结构问题。",
    boundary:
      "它没有比较两个选项，也没有推荐；只把「代价」补进结构清单。线索表会漏同义说法，漏了只报缺口，不硬凑。",
  },
  {
    id: "code",
    no: "06",
    subject: "代码 · 通用入口",
    verdict: "只问结构，不自动跑",
    state: "intake",
    title: "代码摆出来了，系统也不猜 bug 在哪",
    problem:
      "这段代码的结果不对：def add(a, b): return a - b；print(add(2, 3))  # 期望 5，实际 -1",
    student:
      "目标是让 add(2, 3) 返回 5；已知它现在返回 -1，也没有报错；约束是不能改测试。我看了一遍，觉得是 print 写错了。",
    turns: [
      {
        ask: "入口先问（一次只问一个）",
        answer: "最小复现是什么：哪段代码、什么输入、完整报错？",
      },
      {
        ask: "学生补上复现",
        answer: "我跑了 add(2, 3)，返回 -1；预期是 5。",
      },
      {
        ask: "工具轨迹（v0.3，规则模式）",
        answer:
          "check_structure ok：看到 5 项结构、缺口 1 个；run_tests skipped：执行开关关闭，没有运行；ask_clarifying ok：kind=check，answered=1/3。",
      },
    ],
    notes: [
      "代码不是从题面抽的：这次显式提交了 2 行 Python 和一个 unittest；入口只把题面当文本。",
      "「返回 -1」是学生写的，不是系统跑出来的；本轮 SYNAPSE_EXEC=off，执行步是 skipped；打开后同一步会真的跑测试，运行结果可能是 fail，仍不是诊断。",
      "领域标签是显式写的 programming，不是自动识别；代码里的等号和括号很容易被数学线索抢走。",
      "线索表只认动作词：只说「最小复现是…」而没有「跑了 / 试过」时，可能仍报缺复现；这段用了「我跑了…」。",
    ],
    outcome:
      "状态 CLOSED；没有卡点卡。补上复现后仍缺「已经试过哪些改动」，轨迹只问结构，不判断 bug 在哪。",
    boundary:
      "它没有说 return a - b 就是 bug，也没有自动执行；skipped 不是 pass，跑出 fail 也只表示提交的测试没过。",
  },
];

export default function CasesPage() {
  return (
    <div className="sm-about sm-cases">
      <section className="sm-about-hero">
        <Plane>
          <p className="sm-eyebrow">
            <span aria-hidden="true" className="sm-dot" />
            演示记录 · 六段 transcript
          </p>

          <h1 className="sm-display">
            六段记录，
            <span className="sm-display-2">六种收束。</span>
          </h1>

          <p className="sm-lede">
            下面六段来自三次实跑：2026-10-31 的四段诊断记录（数学错步出卡、空白入口给示例、
            物理五轮后弃权、语文只给结构提示），2026-11-01 新增的通用入口记录
            （决策问题，离线规则路径），以及同日的代码问题记录（显式提交、执行开关默认关闭）。
            文字按 transcript 抄录，只做截断。
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
            六段记录
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
                <code>python scripts/demo/walkthrough.py</code> 走六段并写{" "}
                <code>var/demo/walkthrough.md</code>；<code>--no-live</code>{" "}
                只跑标注题、空白、通用入口与代码，物理 / 语文显式跳过；
                <code>--case decision</code> 或 <code>--case code</code> 可单跑。
                代码默认不执行，<code>SYNAPSE_EXEC=on</code> 才会真的跑。
              </p>
            </div>

            <div className="sm-tile sm-about-card sm-about-card--quiet">
              <b>重跑会变吗</b>
              <p>
                数学、空白与通用入口走规则路径，记录稳定；代码也走规则路径，
                但执行状态取决于 <code>SYNAPSE_EXEC</code>；物理与语文依赖实时建图，
                换模型或断网会变。变的是链路，不是准确率。
              </p>
            </div>
          </div>

          <p className="sm-fine">
            这些记录能证明六件事：入口能识别并收束、证据不足时会停、示例不含答案、结构提示不冒充诊断、通用入口不替你做选择、代码不猜也不自动跑。
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