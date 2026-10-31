import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgePanel } from "./KnowledgePanel";
import { searchKnowledge } from "@/src/lib/api/client";
import type { KnowledgeSearch } from "@/src/lib/api/types";

vi.mock("@/src/lib/api/client", () => ({
  searchKnowledge: vi.fn(),
}));

const HITS: KnowledgeSearch = {
  version: "0.1",
  enabled: true,
  query: "恒成立与最值",
  hits: [
    {
      card_id: "K_MATH_MAX_MIN",
      title: "恒成立先转成最值",
      excerpt: "恒成立等价于最值不等式，先确认定义域和端点。",
      source: {
        title: "OpenStax Calculus Volume 1",
        url: "https://openstax.org/details/books/calculus-volume-1",
        license: "CC BY-NC-SA 4.0",
      },
      score: 0.75,
    },
  ],
};

describe("KnowledgePanel", () => {
  beforeEach(() => {
    vi.mocked(searchKnowledge).mockReset();
  });

  it("stays invisible when retrieval is disabled", async () => {
    vi.mocked(searchKnowledge).mockResolvedValue({
      version: "0.1",
      enabled: false,
      query: "恒成立与最值",
      hits: [],
    });

    const { container } = render(
      <KnowledgePanel query="恒成立与最值" subject="math" />,
    );

    await waitFor(() => expect(searchKnowledge).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the explanation with its source and the non-diagnosis note", async () => {
    vi.mocked(searchKnowledge).mockResolvedValue(HITS);

    render(<KnowledgePanel query="恒成立与最值" subject="math" />);

    expect(await screen.findByText("恒成立先转成最值")).toBeInTheDocument();
    expect(screen.getByText(/不是对你这次作答的判断/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "OpenStax Calculus Volume 1" }),
    ).toHaveAttribute(
      "href",
      "https://openstax.org/details/books/calculus-volume-1",
    );
    expect(screen.getByText(/CC BY-NC-SA 4.0/)).toBeInTheDocument();
  });

  it("hides itself when retrieval fails, without covering the diagnosis", async () => {
    vi.mocked(searchKnowledge).mockRejectedValue(new Error("503"));

    const { container } = render(
      <KnowledgePanel query="恒成立与最值" subject="math" />,
    );

    await waitFor(() => expect(searchKnowledge).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});