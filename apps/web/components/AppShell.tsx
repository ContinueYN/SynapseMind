import Link from "next/link";
import type { ReactNode } from "react";

import { Ground } from "@/components/Ground";
import { PointerField } from "@/components/PointerField";
import { ScrollRule } from "@/components/ScrollRule";
import { TopBar } from "@/components/TopBar";
import { Transit } from "@/components/Transit";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="sm-app">
      <Ground />
      <PointerField />
      <ScrollRule />
      <Transit />

      <header className="sm-top">
        <div className="sm-shell sm-top-in">
          <Link className="sm-brand" href="/">
            <svg aria-hidden="true" className="sm-mark" fill="none" viewBox="0 0 24 24">
              <path
                className="sm-mark-link"
                d="M5.5 17.5 12 12l6.5-5.5"
                stroke="currentColor"
                strokeLinecap="round"
                strokeWidth="1.2"
              />
              <circle cx="5.5" cy="17.5" fill="currentColor" r="1.9" />
              <circle cx="18.5" cy="6.5" fill="currentColor" r="1.9" />
              <circle
                className="sm-mark-pulse"
                cx="12"
                cy="12"
                r="2.8"
                stroke="currentColor"
                strokeWidth="0.9"
              />
            </svg>
            <span>SynapseMind</span>
            <span className="sm-brand-sub">单题诊断</span>
          </Link>

          <TopBar />
        </div>
      </header>

      <main className="sm-main">
        <div className="sm-shell">{children}</div>
      </main>

      <div className="sm-shell">
        <footer className="sm-foot">
          <span>目前只支持一道示例题：高中数学 · 函数与导数</span>
          <span>SynapseMind</span>
        </footer>
      </div>
    </div>
  );
}