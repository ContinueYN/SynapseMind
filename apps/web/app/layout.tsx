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
    <html lang="zh-CN" data-scroll-behavior="smooth">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}