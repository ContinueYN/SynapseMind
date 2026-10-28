import Link from "next/link";
import type { ReactNode } from "react";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-frame">
      <header className="site-header">
        <Link className="brand" href="/">
          <span className="brand-mark" aria-hidden="true">
            S
          </span>
          <span>
            <strong>SynapseMind</strong>
            <small>突触智学</small>
          </span>
        </Link>
        <p className="header-line">不是讲这道题，是找到你卡住的那一步。</p>
      </header>
      <main className="page-shell">{children}</main>
      <footer className="site-footer">
        <span>单题诊断引导 · v0.1 walking skeleton</span>
        <span>学习模式不展示最终答案</span>
      </footer>
    </div>
  );
}