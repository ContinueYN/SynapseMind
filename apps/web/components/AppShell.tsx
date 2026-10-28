import Link from "next/link";
import type { ReactNode } from "react";

import Aurora from "@/components/reactbits/Aurora";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-root">
      <div className="aurora-background" aria-hidden="true">
        <Aurora
          amplitude={1.1}
          blend={0.55}
          colorStops={["#020617", "#0f766e", "#4338ca"]}
          height={0.42}
          intro={false}
          mouseInteraction={false}
          opacity={0.72}
          scale={1.15}
          speed={0.55}
        />
      </div>
      <div className="page-vignette" aria-hidden="true" />

      <div className="app-frame">
        <header className="site-header">
          <Link className="brand" href="/">
            <span className="brand-mark" aria-hidden="true">
              S
            </span>
            <span className="brand-copy">
              <strong>SynapseMind</strong>
              <small>突触智学 · 单题诊断</small>
            </span>
          </Link>

          <div className="header-side">
            <p className="header-line">不是讲这道题，是找到你卡住的那一步。</p>
            <span className="header-pill">
              <span className="pulse-dot" aria-hidden="true" />
              M1 live
            </span>
          </div>
        </header>

        <main className="page-shell">{children}</main>

        <footer className="site-footer">
          <span>© 2026 SynapseMind · MIT</span>
          <span>学习模式不展示最终答案</span>
        </footer>
      </div>
    </div>
  );
}