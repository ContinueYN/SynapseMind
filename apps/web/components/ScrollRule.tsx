"use client";

import { useEffect } from "react";

/**
 * 页面顶端那根 1px 的阅读线 + 全站唯一的滚动量。
 *
 * `--read`：读到整页的百分之几（顶部液面的宽度）；
 * `--scroll`：滚了多少 px，背景的几层光按不同的系数用它做景深错位。
 * 一个监听器管两件事，滚动里只写 CSS 变量，不触发重渲染。
 */
export function ScrollRule() {
  useEffect(() => {
    const root = document.documentElement;
    let frame = 0;

    function update() {
      frame = 0;
      const max = root.scrollHeight - window.innerHeight;
      const y = window.scrollY;
      const progress = max > 0 ? Math.min(1, Math.max(0, y / max)) : 0;
      root.style.setProperty("--read", `${(progress * 100).toFixed(2)}%`);
      root.style.setProperty("--scroll", `${Math.round(y)}`);
    }

    function schedule() {
      if (!frame) frame = requestAnimationFrame(update);
    }

    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      root.style.removeProperty("--read");
      root.style.removeProperty("--scroll");
    };
  }, []);

  return (
    <div aria-hidden="true" className="sm-rule">
      <i />
    </div>
  );
}