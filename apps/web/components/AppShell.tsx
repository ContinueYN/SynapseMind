import type { ReactNode } from "react";

import { BrandOrb } from "@/components/BrandOrb";
import { Ground } from "@/components/Ground";
import { PointerField } from "@/components/PointerField";
import { ScrollRule } from "@/components/ScrollRule";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="sm-app">
      <Ground />
      <PointerField />
      <ScrollRule />
      <BrandOrb />

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