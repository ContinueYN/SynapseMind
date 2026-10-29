import Link from "next/link";
import type { ReactNode } from "react";

import { Backdrop } from "@/components/Backdrop";
import { GlassCard } from "@/components/GlassCard";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="sm-app">
      <Backdrop />

      <header className="sm-masthead">
        <div className="sm-shell">
          <GlassCard padded={false}>
            <Link className="sm-brand" href="/">
              SynapseMind <small>突触智学 · 单题诊断</small>
            </Link>
            <span className="sm-masthead-meta">学习模式 · 不给最终答案</span>
          </GlassCard>
        </div>
      </header>

      <main className="sm-main">
        <div className="sm-shell">{children}</div>
      </main>

      <div className="sm-shell">
        <footer className="sm-foot">
          <span>单题诊断 · 一次只定位一个卡点</span>
          <span>SynapseMind</span>
        </footer>
      </div>
    </div>
  );
}