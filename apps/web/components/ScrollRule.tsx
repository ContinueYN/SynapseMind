"use client";

import { useEffect } from "react";

/**
 * 页面顶端那根 1px 的阅读线。
 *
 * 整页是一张纸，滚到哪儿就画到哪儿——它替代了“进度条”，也替代了装饰性的渐变。
 */
export function ScrollRule() {
  useEffect(() => {
    const root = document.documentElement;
    let frame = 0;

    function update() {
      frame = 0;
      const max = root.scrollHeight - window.innerHeight;
      const progress = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
      root.style.setProperty("--read", `${(progress * 100).toFixed(2)}%`);
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
    };
  }, []);

  return (
    <div aria-hidden="true" className="sm-rule">
      <i />
    </div>
  );
}