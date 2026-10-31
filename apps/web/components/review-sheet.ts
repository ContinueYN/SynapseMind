/**
 * 教师复核页的纯逻辑：判断词表、CSV 生成、本机草稿。
 *
 * 这些函数不碰 React，也不发请求；页面组件只负责取数、状态与排版。
 * 判断只存在浏览器里（localStorage）并导出 CSV，不写回复核库。
 */

import type { ReviewItem } from "@/src/lib/api/types";

/** 空串 = 还没判断。三个词与 CLI 复核表的表头一致。 */
export type ReviewJudgment = "" | "accurate" | "plausible_wrong" | "vague";

export interface ReviewDraft {
  judgment: ReviewJudgment;
  note: string;
}

export type ReviewDrafts = Record<string, ReviewDraft>;

export const REVIEW_DRAFTS_KEY = "synapse.review.drafts.v1";

export const REVIEW_JUDGMENTS: ReadonlyArray<{
  value: Exclude<ReviewJudgment, "">;
  label: string;
}> = [
  { value: "accurate", label: "准确" },
  { value: "plausible_wrong", label: "说得通但不对" },
  { value: "vague", label: "空泛" },
];

const JUDGMENT_LABELS: Record<Exclude<ReviewJudgment, "">, string> = {
  accurate: "准确",
  plausible_wrong: "说得通但不对",
  vague: "空泛",
};

const CSV_HEADER = [
  "时间",
  "会话",
  "题目",
  "层级",
  "节点",
  "置信",
  "卡面标签",
  "卡面结论",
  "人工判断",
  "备注",
] as const;

export function judgmentLabel(value: ReviewJudgment): string {
  return value ? JUDGMENT_LABELS[value] : "";
}

/**
 * CSV 转义 + 公式注入防护。
 *
 * 以 `= + - @` 开头的单元格在 Excel 里会被当公式；复核表来自模型生成的卡面，
 * 不能假定它永远是普通文本，所以加一个前导单引号（Excel 不显示它）。
 */
function csvCell(value: string | number): string {
  let text = String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function buildReviewCsv(items: ReviewItem[], drafts: ReviewDrafts): string {
  const rows = items.map((item) => {
    const draft = drafts[item.session_id];
    return [
      item.created_at,
      item.session_id,
      item.problem_id,
      item.layer,
      item.node_id,
      item.confidence.toFixed(2),
      item.label,
      item.one_line,
      judgmentLabel(draft?.judgment ?? ""),
      draft?.note.trim() ?? "",
    ]
      .map(csvCell)
      .join(",");
  });
  return [CSV_HEADER.join(","), ...rows].join("\r\n");
}

/** 本地时间文件名，避免同名覆盖：review-20261031-1653.csv。 */
export function reviewCsvFilename(now: Date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return [
    "review",
    `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`,
    `${pad(now.getHours())}${pad(now.getMinutes())}`,
  ].join("-").concat(".csv");
}

/**
 * 触发浏览器下载。CSV 带 UTF-8 BOM，Windows Excel 打开中文才不乱码。
 */
export function downloadReviewCsv(csv: string, filename: string): void {
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isReviewJudgment(value: unknown): value is ReviewJudgment {
  return (
    typeof value === "string" &&
    ["", "accurate", "plausible_wrong", "vague"].includes(value)
  );
}

/** 读本机草稿；损坏的 JSON 或旧格式一律当作没有，不让页面崩。 */
export function parseReviewDrafts(raw: string | null): ReviewDrafts {
  if (!raw) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return {};
  }
  if (!isRecord(parsed)) return {};

  const drafts: ReviewDrafts = {};
  for (const [sessionId, value] of Object.entries(parsed)) {
    if (!isRecord(value) || !isReviewJudgment(value.judgment)) continue;
    const note = typeof value.note === "string" ? value.note.slice(0, 500) : "";
    drafts[sessionId] = { judgment: value.judgment, note };
  }
  return drafts;
}

export function serializeReviewDrafts(drafts: ReviewDrafts): string {
  return JSON.stringify(drafts);
}

export function loadReviewDrafts(storage: Pick<Storage, "getItem">): ReviewDrafts {
  try {
    return parseReviewDrafts(storage.getItem(REVIEW_DRAFTS_KEY));
  } catch {
    return {};
  }
}

export function saveReviewDrafts(
  storage: Pick<Storage, "setItem">,
  drafts: ReviewDrafts,
): void {
  try {
    storage.setItem(REVIEW_DRAFTS_KEY, serializeReviewDrafts(drafts));
  } catch {
    // 隐私模式/配额满：判断仍留在页面里，只是刷新后不保留。
  }
}