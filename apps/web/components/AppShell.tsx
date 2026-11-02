import type { ReactNode } from "react";
import Link from "next/link";

import { AccountMenu } from "@/components/AccountMenu";
import { BrandOrb } from "@/components/BrandOrb";
import { Ground } from "@/components/Ground";
import { PointerField } from "@/components/PointerField";
import { ScrollMemory } from "@/components/ScrollMemory";
import { ScrollRule } from "@/components/ScrollRule";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="sm-app">
      <Ground />
      <PointerField />
      <ScrollRule />
      <ScrollMemory />
      <BrandOrb />
      <AccountMenu />

      <main className="sm-main">
        <div className="sm-shell">{children}</div>
      </main>

      <div className="sm-shell">
        <footer className="sm-foot">
          <span>通用问题诊断 · 自托管 · 数学、写作、代码与生活决策</span>
          <span className="sm-foot-links">
            <Link className="sm-foot-link" href="/cases">
              演示记录
            </Link>
            <Link className="sm-foot-link" href="/science">
              科学依据
            </Link>
            <Link className="sm-foot-link" href="/about">
              为什么这样设计
            </Link>
            <span>SynapseMind</span>
          </span>
        </footer>
      </div>
    </div>
  );
}