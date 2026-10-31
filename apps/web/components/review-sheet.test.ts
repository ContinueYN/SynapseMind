import { describe, expect, it, vi } from "vitest";

import {
  REVIEW_DRAFTS_KEY,
  buildReviewCsv,
  judgmentLabel,
  loadReviewDrafts,
  parseReviewDrafts,
  reviewCsvFilename,
  saveReviewDrafts,
  serializeReviewDrafts,
  type ReviewDrafts,
} from "./review-sheet";
import type { ReviewItem } from "@/src/lib/api/types";

const ITEM: ReviewItem = {
  session_id: "S_ABC123456789",
  problem_id: "P_PUB_002",
  layer: "L2",
  label: "概念不清：恒成立与最值",
  node_id: "n3",
  one_line: "漏掉了 a≤0 这一支。",
  confidence: 0.86,
  created_at: "2026-10-31T08:00:00+00:00",
};

const DRAFTS: ReviewDrafts = {
  S_ABC123456789: {
    judgment: "accurate",
    note: "定义域那步说错了",
  },
};

describe("buildReviewCsv", () => {
  it("writes a header and one row per queue item", () => {
    const csv = buildReviewCsv([ITEM], DRAFTS);
    const lines = csv.split("\r\n");

    expect(lines[0]).toBe(
      "时间,会话,题目,层级,节点,置信,卡面标签,卡面结论,人工判断,备注",
    );
    expect(lines[1]).toBe(
      "2026-10-31T08:00:00+00:00,S_ABC123456789,P_PUB_002,L2,n3,0.86," +
        "概念不清：恒成立与最值,漏掉了 a≤0 这一支。,准确,定义域那步说错了",
    );
    expect(lines).toHaveLength(2);
  });

  it("keeps an unjudged row blank instead of inventing a label", () => {
    const csv = buildReviewCsv([ITEM], {});
    const row = csv.split("\r\n")[1];

    expect(row.endsWith(",,")).toBe(true);
    expect(row).not.toContain("准确");
  });

  it("quotes separators, quotes and newlines", () => {
    const tricky: ReviewItem = {
      ...ITEM,
      label: 'A,B "C"\nD',
      one_line: "第一行\n第二行",
    };

    const csv = buildReviewCsv([tricky], {});
    const row = csv.split("\r\n")[1];

    expect(row).toContain('"A,B ""C""\nD"');
    expect(row).toContain('"第一行\n第二行"');
  });

  it("does not let a card cell run as an Excel formula", () => {
    const csv = buildReviewCsv([{ ...ITEM, one_line: "=SUM(A1)" }], {});

    expect(csv.split("\r\n")[1]).toContain("'=SUM(A1)");
  });

  it("exports every item in queue order", () => {
    const second: ReviewItem = {
      ...ITEM,
      session_id: "S_DEF987654321",
      one_line: "只讨论了 a>0。",
    };
    const csv = buildReviewCsv([second, ITEM], {});

    expect(csv.indexOf("S_DEF987654321")).toBeLessThan(
      csv.indexOf("S_ABC123456789"),
    );
  });
});

describe("judgmentLabel", () => {
  it("uses the same three words as the review sheet", () => {
    expect(judgmentLabel("accurate")).toBe("准确");
    expect(judgmentLabel("plausible_wrong")).toBe("说得通但不对");
    expect(judgmentLabel("vague")).toBe("空泛");
    expect(judgmentLabel("")).toBe("");
  });
});

describe("reviewCsvFilename", () => {
  it("stamps local date and minute", () => {
    expect(reviewCsvFilename(new Date(2026, 9, 31, 16, 5))).toBe(
      "review-20261031-1605.csv",
    );
  });
});

describe("review draft storage", () => {
  it("round-trips valid drafts", () => {
    expect(parseReviewDrafts(serializeReviewDrafts(DRAFTS))).toEqual(DRAFTS);
  });

  it("treats missing or broken storage as no drafts", () => {
    expect(parseReviewDrafts(null)).toEqual({});
    expect(parseReviewDrafts("not json")).toEqual({});
    expect(parseReviewDrafts("[]")).toEqual({});
    expect(parseReviewDrafts('{"S_X":{"judgment":"maybe","note":"x"}}')).toEqual(
      {},
    );
  });

  it("clips a long note and ignores unknown fields", () => {
    const parsed = parseReviewDrafts(
      JSON.stringify({
        S_X: { judgment: "vague", note: "x".repeat(600), extra: true },
      }),
    );

    expect(parsed.S_X).toEqual({ judgment: "vague", note: "x".repeat(500) });
  });

  it("swallows storage errors in both directions", () => {
    expect(
      loadReviewDrafts({
        getItem: () => {
          throw new Error("blocked");
        },
      }),
    ).toEqual({});

    const setItem = vi.fn(() => {
      throw new Error("quota");
    });
    expect(() => saveReviewDrafts({ setItem }, DRAFTS)).not.toThrow();
    expect(setItem).toHaveBeenCalledWith(REVIEW_DRAFTS_KEY, expect.any(String));
  });
});