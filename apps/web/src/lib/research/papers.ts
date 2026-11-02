/**
 * Curated research basis for the diagnosis design.
 *
 * Every entry below was checked against Crossref / PubMed before being added:
 * title, first author, year, venue and DOI. The DOI is the canonical link, so
 * a reader can land on the publisher's record instead of trusting this file.
 *
 * Boundary: these papers explain where the design shapes came from. They are
 * not evidence that this product works. No controlled experiment, no delayed
 * post-test, no effect size of ours is claimed anywhere in this module.
 */

export interface ResearchPaper {
  id: string;
  title: string;
  /** Short citation form; full author list is available at the DOI. */
  authors: string;
  year: number;
  venue: string;
  doi: string;
  url: string;
  /** One sentence: the design shape borrowed, not a finding we replicated. */
  borrow: string;
}

export const PAPERS = [
  {
    id: "citri-malenka-2008",
    title: "Synaptic plasticity: Multiple forms, functions, and mechanisms",
    authors: "Citri & Malenka",
    year: 2008,
    venue: "Neuropsychopharmacology 33, 18–41",
    doi: "10.1038/sj.npp.1301559",
    url: "https://doi.org/10.1038/sj.npp.1301559",
    borrow: "只借「成功提取会强化同一条通路」的更新形状，不做脑测量。",
  },
  {
    id: "kandel-2001",
    title:
      "The molecular biology of memory storage: A dialogue between genes and synapses",
    authors: "Kandel",
    year: 2001,
    venue: "Science 294, 1030–1038",
    doi: "10.1126/science.1067020",
    url: "https://doi.org/10.1126/science.1067020",
    borrow: "借「短期记忆要经过重复与巩固才稳定」的方向，不借分子层面的结论。",
  },
  {
    id: "mcgaugh-2000",
    title: "Memory—A century of consolidation",
    authors: "McGaugh",
    year: 2000,
    venue: "Science 287, 248–251",
    doi: "10.1126/science.287.5451.248",
    url: "https://doi.org/10.1126/science.287.5451.248",
    borrow: "新记忆需要时间巩固，所以验证排到 24 小时后，而不是当场判定学会。",
  },
  {
    id: "nader-2000",
    title:
      "Fear memories require protein synthesis in the amygdala for reconsolidation after retrieval",
    authors: "Nader, Schafe & LeDoux",
    year: 2000,
    venue: "Nature 406, 722–726",
    doi: "10.1038/35021052",
    url: "https://doi.org/10.1038/35021052",
    borrow: "提取会让旧记忆短暂变得可改，所以先问「你当时怎么想」，再给新信息。",
  },
  {
    id: "schultz-1997",
    title: "A neural substrate of prediction and reward",
    authors: "Schultz, Dayan & Montague",
    year: 1997,
    venue: "Science 275, 1593–1599",
    doi: "10.1126/science.275.5306.1593",
    url: "https://doi.org/10.1126/science.275.5306.1593",
    borrow: "先让学生给出预期，再对照结果；预期被打破的地方才是更新点。",
  },
  {
    id: "bayer-glimcher-2005",
    title:
      "Midbrain dopamine neurons encode a quantitative reward prediction error signal",
    authors: "Bayer & Glimcher",
    year: 2005,
    venue: "Neuron 47, 129–141",
    doi: "10.1016/j.neuron.2005.05.020",
    url: "https://doi.org/10.1016/j.neuron.2005.05.020",
    borrow: "把「差多少」而不只是「对或错」当作反馈信号。",
  },
  {
    id: "roediger-karpicke-2006",
    title:
      "Test-enhanced learning: Taking memory tests improves long-term retention",
    authors: "Roediger & Karpicke",
    year: 2006,
    venue: "Psychological Science 17, 249–255",
    doi: "10.1111/j.1467-9280.2006.01693.x",
    url: "https://doi.org/10.1111/j.1467-9280.2006.01693.x",
    borrow: "先问不先讲：回忆本身就是练习，不等同于再读一遍。",
  },
  {
    id: "karpicke-blunt-2011",
    title:
      "Retrieval practice produces more learning than elaborative studying with concept mapping",
    authors: "Karpicke & Blunt",
    year: 2011,
    venue: "Science 331, 772–775",
    doi: "10.1126/science.1199327",
    url: "https://doi.org/10.1126/science.1199327",
    borrow: "把「合意困难」写进流程：当下更费劲的提取，可能留下更久。",
  },
  {
    id: "sweller-1988",
    title: "Cognitive load during problem solving: Effects on learning",
    authors: "Sweller",
    year: 1988,
    venue: "Cognitive Science 12, 257–285",
    doi: "10.1207/s15516709cog1202_4",
    url: "https://doi.org/10.1207/s15516709cog1202_4",
    borrow: "先降低外在负荷，一次只给一个最小动作。",
  },
  {
    id: "sweller-cooper-1985",
    title:
      "The use of worked examples as a substitute for problem solving in learning algebra",
    authors: "Sweller & Cooper",
    year: 1985,
    venue: "Cognition and Instruction 2, 59–89",
    doi: "10.1207/s1532690xci0201_3",
    url: "https://doi.org/10.1207/s1532690xci0201_3",
    borrow: "完全没思路时先给 1–2 步起步示例，再回到自己的题。",
  },
  {
    id: "hattie-timperley-2007",
    title: "The power of feedback",
    authors: "Hattie & Timperley",
    year: 2007,
    venue: "Review of Educational Research 77, 81–112",
    doi: "10.3102/003465430298487",
    url: "https://doi.org/10.3102/003465430298487",
    borrow: "反馈指向任务、过程和下一步，不指向「你这个人」。",
  },
  {
    id: "kluger-denisi-1996",
    title:
      "The effects of feedback interventions on performance: A historical review, a meta-analysis, and a preliminary feedback intervention theory",
    authors: "Kluger & DeNisi",
    year: 1996,
    venue: "Psychological Bulletin 119, 254–284",
    doi: "10.1037/0033-2909.119.2.254",
    url: "https://doi.org/10.1037/0033-2909.119.2.254",
    borrow: "避免把反馈做成对人的评价；评价性反馈可能反而降低表现。",
  },
  {
    id: "baddeley-2003",
    title: "Working memory: Looking back and looking forward",
    authors: "Baddeley",
    year: 2003,
    venue: "Nature Reviews Neuroscience 4, 829–839",
    doi: "10.1038/nrn1201",
    url: "https://doi.org/10.1038/nrn1201",
    borrow: "把工作记忆当作有限的工作台，控制一次要同时处理的信息量。",
  },
  {
    id: "cowan-2001",
    title:
      "The magical number 4 in short-term memory: A reconsideration of mental storage capacity",
    authors: "Cowan",
    year: 2001,
    venue: "Behavioral and Brain Sciences 24, 87–114",
    doi: "10.1017/S0140525X01003922",
    url: "https://doi.org/10.1017/S0140525X01003922",
    borrow: "一次只推进一个最小动作，不堆叠并列问题。",
  },
  {
    id: "horn-cattell-1966",
    title:
      "Refinement and test of the theory of fluid and crystallized general intelligences",
    authors: "Horn & Cattell",
    year: 1966,
    venue: "Journal of Educational Psychology 57, 253–270",
    doi: "10.1037/h0023816",
    url: "https://doi.org/10.1037/h0023816",
    borrow: "把能力拆成几个可分别描述的广域维度，而不是一个总分。",
  },
  {
    id: "mcgrew-2009",
    title:
      "CHC theory and the human cognitive abilities project: Standing on the shoulders of the giants of psychometric intelligence research",
    authors: "McGrew",
    year: 2009,
    venue: "Intelligence 37, 1–10",
    doi: "10.1016/j.intell.2008.08.004",
    url: "https://doi.org/10.1016/j.intell.2008.08.004",
    borrow: "沿用 CHC 的广域维度命名，让七维标签可核对、可讨论。",
  },
] as const satisfies readonly ResearchPaper[];

export type ResearchPaperId = (typeof PAPERS)[number]["id"];

export interface ResearchPrinciple {
  id: string;
  label: string;
  english: string;
  /** One sentence: the mechanism as we use it. */
  mechanism: string;
  paperIds: readonly ResearchPaperId[];
  /** Explicit boundary: what this principle does not license us to say. */
  notClaiming: string;
}

export const PRINCIPLES = [
  {
    id: "plasticity",
    label: "强化与更新",
    english: "Plasticity / LTP",
    mechanism:
      "一条通路被成功调用后会暂时变强，失败或久不用会变弱；更新是按结果调权重，不是一次性写入。",
    paperIds: ["citri-malenka-2008", "kandel-2001"],
    notClaiming:
      "不测量大脑活动，也不声称用户身上发生了 LTP；只借用更新规则，不借用神经机制。",
  },
  {
    id: "reconsolidation",
    label: "记忆再巩固",
    english: "Consolidation / reconsolidation",
    mechanism:
      "旧记忆在被重新提取时会短暂进入可改写状态；新信息在这段窗口里更容易接上。",
    paperIds: ["mcgaugh-2000", "nader-2000"],
    notClaiming:
      "不声称追问会改写记忆痕迹；没有做神经或生化测量，「可改写」不是我们对用户的断言。",
  },
  {
    id: "prediction-error",
    label: "预测误差",
    english: "Prediction error",
    mechanism:
      "学习主要由「实际结果减去预期」驱动：预期被打破的地方，更新最大。",
    paperIds: ["schultz-1997", "bayer-glimcher-2005"],
    notClaiming:
      "不把多巴胺信号当成学习效果；只借用「先预期、再对照」的顺序。",
  },
  {
    id: "retrieval",
    label: "提取练习与合意困难",
    english: "Retrieval practice",
    mechanism:
      "先尝试回忆、再得到反馈，比反复阅读留下更久的记忆；当下更费劲不等于没学到。",
    paperIds: ["roediger-karpicke-2006", "karpicke-blunt-2011"],
    notClaiming:
      "不证明我们的追问能提高延迟正确率；没有对照实验，也不承诺提分。",
  },
  {
    id: "load",
    label: "认知负荷与示例",
    english: "Cognitive load",
    mechanism:
      "工作记忆容量有限；对新手，先看一个围住当前动作的示例，比同时搜索解法和目标更省负荷。",
    paperIds: ["sweller-1988", "sweller-cooper-1985"],
    notClaiming:
      "不声称示例一定优于讲解；示例只示范起步，不替学生走完，也没有做示例渐隐实验。",
  },
  {
    id: "feedback",
    label: "反馈",
    english: "Feedback",
    mechanism:
      "反馈要指向任务、过程和下一步，而不是指向人；指向「你怎样」的反馈常常没有帮助，甚至有害。",
    paperIds: ["hattie-timperley-2007", "kluger-denisi-1996"],
    notClaiming:
      "不声称卡面措辞已被验证；没有做反馈方式的对照比较。",
  },
  {
    id: "working-memory",
    label: "工作记忆",
    english: "Working memory",
    mechanism:
      "同时保持和操作的信息只有很少几项；一次只推进一个最小动作，是为了不把容量耗在切换上。",
    paperIds: ["baddeley-2003", "cowan-2001"],
    notClaiming:
      "不估计任何人的工作记忆容量；七维标签只描述题目，不描述人。",
  },
  {
    id: "chc",
    label: "CHC 广域能力",
    english: "CHC broad abilities",
    mechanism:
      "认知能力更适合用一组广域维度分类描述，而不是压成一个总分；分类能说「这道题需要什么」，不能说「你有多聪明」。",
    paperIds: ["horn-cattell-1966", "mcgrew-2009"],
    notClaiming:
      "CHC 在这里只是题目需求标签空间，不是对人的测评；不给个人打分、排序或贴标签。",
  },
] as const satisfies readonly ResearchPrinciple[];

/** The one sentence that must travel with every rendering of this section. */
export const RESEARCH_BOUNDARY =
  "这些文献解释设计来源，不证明本产品有效；没有对照实验或提分数据。";

export const PAPERS_BY_ID = Object.fromEntries(
  PAPERS.map((paper) => [paper.id, paper]),
) as Record<ResearchPaperId, ResearchPaper>;

export function papersFor(principle: ResearchPrinciple): readonly ResearchPaper[] {
  return principle.paperIds.map((id) => PAPERS_BY_ID[id]);
}