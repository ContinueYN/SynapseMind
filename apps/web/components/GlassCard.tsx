"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * 一块玻璃 = 五层光学 + 一层内容。
 *
 * 折射这一层是真的：读背景光斑在页面上的真实坐标，
 * 换算成这块玻璃的局部百分比，写进 --p1x/--p2x/--p3x。
 * 所以玻璃后面的光斑会跟着背后的光斑走，不是一张贴图。
 */

const CARDS = new Set<HTMLElement>();
let frame = 0;
let listening = false;

function syncRefraction() {
  const blobs = Array.from(document.querySelectorAll<HTMLElement>(".sm-blob")).slice(0, 3);
  if (blobs.length === 0) return;

  const centers = blobs.map((blob) => {
    const rect = blob.getBoundingClientRect();
    return [rect.left + rect.width / 2, rect.top + rect.height / 2] as const;
  });

  CARDS.forEach((el) => {
    const rect = el.getBoundingClientRect();
    if (rect.bottom < -240 || rect.top > window.innerHeight + 240) return;
    centers.forEach((center, index) => {
      const x = (((center[0] - rect.left) / rect.width) * 100).toFixed(1);
      const y = (((center[1] - rect.top) / rect.height) * 100).toFixed(1);
      el.style.setProperty(`--p${index + 1}x`, `${x}%`);
      el.style.setProperty(`--p${index + 1}y`, `${y}%`);
    });
  });
}

function scheduleSync() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    syncRefraction();
  });
}

function onScrollOrResize() {
  scheduleSync();
}

/** 答完一闪：一道高光扫过整块玻璃。 */
export function shineGlass(el: HTMLElement | null) {
  if (!el) return;
  el.classList.add("sm-shine");
  window.setTimeout(() => el.classList.remove("sm-shine"), 980);
}

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  id?: string;
  /** 面板自带内边距；想要贴边布局时关掉 */
  padded?: boolean;
}

export function GlassCard({ children, className = "", id, padded = true }: GlassCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const rectRef = useRef<DOMRect | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    /* 闭包里用非空引用，别让 narrowing 在函数声明里失效 */
    const node = el;

    CARDS.add(node);
    scheduleSync();

    if (!listening) {
      listening = true;
      window.addEventListener("scroll", onScrollOrResize, { passive: true });
      window.addEventListener("resize", onScrollOrResize, { passive: true });
    }

    function readRect() {
      rectRef.current = node.getBoundingClientRect();
    }

    function onEnter() {
      readRect();
    }

    function onMove(event: PointerEvent) {
      const rect = rectRef.current;
      if (!rect || rect.width === 0) return;
      const px = (event.clientX - rect.left) / rect.width;
      const py = (event.clientY - rect.top) / rect.height;
      node.style.setProperty("--mx", `${(px * 100).toFixed(1)}%`);
      node.style.setProperty("--my", `${(py * 100).toFixed(1)}%`);
      node.style.setProperty("--sx", `${((px - 0.5) * -36).toFixed(1)}%`);
      node.style.setProperty("--lx", `${((px - 0.5) * -30).toFixed(1)}px`);
      node.style.setProperty("--ly", `${((py - 0.5) * -20).toFixed(1)}px`);
    }

    function onLeave() {
      node.style.setProperty("--sx", "0%");
      node.style.setProperty("--lx", "0px");
      node.style.setProperty("--ly", "0px");
      rectRef.current = null;
    }

    node.addEventListener("pointerenter", onEnter);
    node.addEventListener("pointermove", onMove);
    node.addEventListener("pointerleave", onLeave);

    return () => {
      CARDS.delete(node);
      node.removeEventListener("pointerenter", onEnter);
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  return (
    <div className={`sm-glass ${className}`.trim()} id={id} ref={ref}>
      <span aria-hidden="true" className="sm-lens" />
      <span aria-hidden="true" className="sm-streak" />
      <span aria-hidden="true" className="sm-spec" />
      <span aria-hidden="true" className="sm-chroma" />
      <span aria-hidden="true" className="sm-frost" />
      <div className={`sm-glass-in ${padded ? "" : "sm-glass-in-flush"}`.trim()}>
        {children}
      </div>
    </div>
  );
}