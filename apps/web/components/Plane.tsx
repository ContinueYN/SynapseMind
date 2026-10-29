"use client";

import type { ReactNode } from "react";

import { useGlass } from "@/components/useGlass";

/**
 * 一块玻璃板：文字的家。
 *
 * 三层都在这一个组件里：
 * - `.sm-plane-glow`：板底下那滩光，玻璃"浮着"靠它；
 * - `.sm-glass-clip`：板里的光与掠过的镜面，只在这块圆角里跑；
 * - `.sm-plane`：板本身（渐变、内壁、边光、颗粒由 CSS 给）。
 *
 * 板不裁切（`overflow` 放出去），所以段落页签能探出板的上缘。
 * 指针位置只写 CSS 变量，不进 React state——移动鼠标不触发重渲染。
 */
export function Plane({
  children,
  className = "",
  glow = true,
  id,
}: {
  children: ReactNode;
  className?: string;
  /** 板底是否铺那滩光；同一屏两块板挨得近时可以关掉一块 */
  glow?: boolean;
  id?: string;
}) {
  const { ref, onPointerMove, onPointerLeave } = useGlass<HTMLDivElement>();

  return (
    <div className={`sm-plane-wrap ${className}`.trim()} id={id}>
      {glow ? <span aria-hidden="true" className="sm-plane-glow" /> : null}

      <div
        className="sm-plane"
        onPointerLeave={onPointerLeave}
        onPointerMove={onPointerMove}
        ref={ref}
      >
        <span aria-hidden="true" className="sm-glass-clip">
          <span className="sm-sheen" />
        </span>
        <div className="sm-plane-in">{children}</div>
      </div>
    </div>
  );
}