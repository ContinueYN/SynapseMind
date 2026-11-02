import { describe, expect, it } from "vitest";

import {
  PAPERS,
  PAPERS_BY_ID,
  PRINCIPLES,
  RESEARCH_BOUNDARY,
} from "./papers";

const DOI = /^10\.\d{4,9}\/\S+$/;

describe("research papers", () => {
  it("keeps every citation backed by a resolvable DOI link", () => {
    expect(PAPERS).toHaveLength(16);

    for (const paper of PAPERS) {
      expect(paper.doi).toMatch(DOI);
      expect(paper.url).toBe(`https://doi.org/${paper.doi}`);
      expect(paper.year).toBeGreaterThanOrEqual(1960);
      expect(paper.title.length).toBeGreaterThan(12);
      expect(paper.borrow.length).toBeGreaterThan(0);
    }
  });

  it("does not repeat a paper or a DOI", () => {
    expect(new Set(PAPERS.map((paper) => paper.id)).size).toBe(PAPERS.length);
    expect(new Set(PAPERS.map((paper) => paper.doi)).size).toBe(PAPERS.length);
  });

  it("links every principle to existing papers and states a boundary", () => {
    expect(PRINCIPLES).toHaveLength(8);

    for (const principle of PRINCIPLES) {
      expect(principle.paperIds.length).toBeGreaterThan(0);
      expect(principle.mechanism.length).toBeGreaterThan(10);
      expect(principle.notClaiming).toContain("不");

      for (const id of principle.paperIds) {
        expect(PAPERS_BY_ID[id]).toBeDefined();
      }
    }
  });

  it("keeps the shared boundary sentence and avoids ability-score claims", () => {
    expect(RESEARCH_BOUNDARY).toBe(
      "这些文献解释设计来源，不证明本产品有效；没有对照实验或提分数据。",
    );

    const text = JSON.stringify({ PAPERS, PRINCIPLES, RESEARCH_BOUNDARY });
    expect(text).not.toMatch(/IQ|能力分|排名|智商|百分位/);
  });
});