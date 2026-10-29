import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import "./styles/tokens.css";
import "./styles/surface.css";

export const metadata: Metadata = {
  title: "SynapseMind 突触智学",
  description: "交一道不会的题和你的过程，用追问找到你卡住的那一步。",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <head>
        {/* 必须在浏览器恢复滚动之前就关掉它：放在 React 的 effect 里可能已经晚了，
            那一下"先停在页底、再滑到页顶"就是恢复滚动 + 平滑滚动叠加出来的 */}
        <script
          dangerouslySetInnerHTML={{
            __html: 'try{history.scrollRestoration="manual"}catch(e){}',
          }}
        />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}