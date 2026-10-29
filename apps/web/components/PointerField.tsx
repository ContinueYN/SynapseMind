"use client";

import { useEffect } from "react";

/**
 * 指针的位置写进两个变量，供背景的几层光各自取用。
 *
 * 为什么不让它进 state：每帧一次 setState 会把整棵树重渲染。
 * 这里只写 documentElement 上的 --gx / --gy（单位是 −1…1），
 * CSS 里每层乘各自的系数（远的光挪得少、近的挪得多），景深就出来了。
 *
 * 阻尼：每帧只补剩余距离的 12%，指针停了光还漂一小段——这比"跟得死准"更像水。
 */
export function PointerField() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;

    const root = document.documentElement;
    let gx = 0;
    let gy = 0;
    let tx = 0;
    let ty = 0;
    let frame = 0;
    let running = false;

    const tick = () => {
      gx += (tx - gx) * 0.12;
      gy += (ty - gy) * 0.12;
      if (Math.abs(tx - gx) < 0.002 && Math.abs(ty - gy) < 0.002) {
        gx = tx;
        gy = ty;
        running = false;
        root.style.setProperty("--gx", gx.toFixed(3));
        root.style.setProperty("--gy", gy.toFixed(3));
        return;
      }
      root.style.setProperty("--gx", gx.toFixed(3));
      root.style.setProperty("--gy", gy.toFixed(3));
      frame = requestAnimationFrame(tick);
    };

    const onMove = (event: PointerEvent) => {
      tx = (event.clientX / window.innerWidth - 0.5) * 2;
      ty = (event.clientY / window.innerHeight - 0.5) * 2;
      if (!running) {
        running = true;
        frame = requestAnimationFrame(tick);
      }
    };

    const onLeave = () => {
      tx = 0;
      ty = 0;
      if (!running) {
        running = true;
        frame = requestAnimationFrame(tick);
      }
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerleave", onLeave);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerleave", onLeave);
      root.style.removeProperty("--gx");
      root.style.removeProperty("--gy");
    };
  }, []);

  return null;
}