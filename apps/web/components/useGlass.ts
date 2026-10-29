"use client";

import { useCallback, useEffect, useMemo, useRef, type PointerEvent } from "react";

/**
 * 玻璃跟手：把指针位置写进 CSS 变量，再给一点点倾斜。
 *
 * - `--mx/--my`：边框冷光的位置
 * - `--lx/--ly`：玻璃表面那团柔光的位置
 * - `--rx/--ry`：最多 1–1.5 度的倾斜（物理上"光在弯的玻璃上走"）
 *
 * 全部直接写 style，不走 React state：拖鼠标不触发重渲染。
 * 触屏和 reduce-motion 下完全不动。
 */
export function useGlass<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const frame = useRef(0);
  const point = useRef({ x: 0.5, y: 0.5 });
  const still = useMemo(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  const apply = useCallback(() => {
    frame.current = 0;
    const el = ref.current;
    if (!el) return;
    const { x, y } = point.current;
    el.style.setProperty("--mx", `${x * 100}%`);
    el.style.setProperty("--my", `${y * 100}%`);
    el.style.setProperty("--lx", `${14 + x * 72}%`);
    el.style.setProperty("--ly", `${-6 + y * 88}%`);
    el.style.setProperty("--ry", `${(x - 0.5) * 3}deg`);
    el.style.setProperty("--rx", `${(0.5 - y) * 2.1}deg`);
  }, []);

  const onPointerMove = useCallback(
    (event: PointerEvent<T>) => {
      if (still || event.pointerType === "touch") return;
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      point.current = {
        x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
        y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
      };
      if (!frame.current) frame.current = requestAnimationFrame(apply);
    },
    [apply, still],
  );

  const onPointerLeave = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
    el.style.setProperty("--lx", "26%");
    el.style.setProperty("--ly", "0%");
  }, []);

  useEffect(
    () => () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    },
    [],
  );

  return { ref, onPointerMove, onPointerLeave };
}