"use client";

import { useState } from "react";

/**
 * 题面：追问的时候要能随时看到整道题。
 *
 * 默认展开；收起时只露三行（真的没写完的题也能一眼看到开头）。
 * 左侧那列是文档式的标签位，右侧是可读宽度的正文——不加卡片、不加边框。
 */
export function ProblemBrief({
  text,
  defaultOpen = true,
}: {
  text: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const body = text.trim();
  if (!body) return null;

  return (
    <section className="sm-brief" data-open={open}>
      <span className="sm-brief-lab">题面</span>
      <p className="sm-brief-text">{body}</p>
      <button
        aria-expanded={open}
        className="sm-link sm-link-quiet sm-brief-btn"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        {open ? "收起" : "展开整道题"}
      </button>
    </section>
  );
}