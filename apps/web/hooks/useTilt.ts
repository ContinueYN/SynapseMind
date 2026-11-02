"use client";

import { useEffect, useRef } from "react";

/**
 * 一块"会翘的玻璃砖"：指针在砖上时，砖朝指针方向倾一点点，白光跟着指针走。
 *
 * 用事件委托，一个监听覆盖整组砖——不在每一块砖上挂 handler，
 * 也不把指针位置塞进 state（那样每移动一像素就重渲染一次）。
 * 只有带 data-tilt 的元素会被写到，其余位置不动。
 */
export function useTiltZone<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useEffect(() => {
    const zone = ref.current;
    if (!zone) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;

    let active: HTMLElement | null = null;

    const paint = (event: PointerEvent) => {
      const target = (event.target as HTMLElement | null)?.closest?.("[data-tilt]");
      const next = target instanceof HTMLElement ? target : null;
      if (next !== active) {
        active?.removeAttribute("data-lit");
        active = next;
        active?.setAttribute("data-lit", "true");
      }
      if (!active) return;
      const box = active.getBoundingClientRect();
      const x = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
      const y = Math.min(1, Math.max(0, (event.clientY - box.top) / box.height));
      active.style.setProperty("--mx", `${(x * 100).toFixed(1)}%`);
      active.style.setProperty("--my", `${(y * 100).toFixed(1)}%`);
      active.style.setProperty("--ry", `${((x - 0.5) * 2.4).toFixed(2)}deg`);
      active.style.setProperty("--rx", `${((0.5 - y) * 1.8).toFixed(2)}deg`);
    };

    const clear = () => {
      if (!active) return;
      active.removeAttribute("data-lit");
      active.style.removeProperty("--mx");
      active.style.removeProperty("--my");
      active.style.removeProperty("--rx");
      active.style.removeProperty("--ry");
      active = null;
    };

    zone.addEventListener("pointermove", paint, { passive: true });
    zone.addEventListener("pointerleave", clear);
    return () => {
      zone.removeEventListener("pointermove", paint);
      zone.removeEventListener("pointerleave", clear);
      clear();
    };
  }, []);

  return ref;
}