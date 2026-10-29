"use client";

import type { ReactNode } from "react";

import { useGlass } from "@/components/useGlass";

/**
 * 一块琉璃：全站唯一的面。
 *
 * 玻璃本体、冷光、柔光、颗粒、倾斜都在 CSS 里；这里只把指针位置写进变量。
 */

interface SurfaceProps {
  children: ReactNode;
  className?: string;
  id?: string;
  /** 面板自带内边距；想要贴边布局时关掉 */
  padded?: boolean;
}

/**
 * 一块玻璃：抬高一层的那块面（交题板 / 追问卡 / 卡点卡）。
 *
 * 玻璃本体、冷光、柔光、颗粒、倾斜都在 CSS 里；这里只把指针位置写进变量。
 * 板里的光与掠过的镜面放在 `.sm-glass-clip` 里，保证只在圆角内跑。
 */
export function Surface({ children, className = "", id, padded = true }: SurfaceProps) {
  const { ref, onPointerMove, onPointerLeave } = useGlass<HTMLDivElement>();

  return (
    <div
      className={`sm-sheet ${className}`.trim()}
      id={id}
      onPointerLeave={onPointerLeave}
      onPointerMove={onPointerMove}
      ref={ref}
    >
      <span aria-hidden="true" className="sm-glass-clip">
        <span className="sm-sheen" />
      </span>
      <div className={`sm-sheet-in${padded ? "" : " sm-sheet-in-flush"}`.trim()}>
        {children}
      </div>
    </div>
  );
}