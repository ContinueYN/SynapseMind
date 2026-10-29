"use client";

import { useEffect } from "react";

/**
 * 全站唯一的滚动量。
 *
 * `--read-n`：读到整页的百分之几（顶部那颗球外圈的进度环，单位是 0–100 的数）；
 * `--scroll`：滚了多少 px，背景几层光按不同系数用它做景深错位。
 * 一个监听器管两件事，滚动里只写 CSS 变量，不触发重渲染。
 *
 * 另外两件事也归它管，因为都必须在整页挂载时做一次：
 * 1. 关掉浏览器的滚动恢复——否则刷新时会先停在上一屏的位置；
 * 2. 打开站点一律从顶部开始，而且是"瞬间到顶"。
 *    原来 html 上有 `scroll-behavior: smooth`，于是这次归零变成了一段从页底滚到页顶的动画，
 *    就是"先在最下面然后再到最上面"。平滑滚动只该用在页内跳转上（由 scrollIntoView 显式指定）。
 */
export function ScrollRule() {
  useEffect(() => {
    const root = document.documentElement;
    let frame = 0;

    if ("scrollRestoration" in history) {
      history.scrollRestoration = "manual";
    }
    window.scrollTo(0, 0);

    function update() {
      frame = 0;
      const max = root.scrollHeight - window.innerHeight;
      const y = window.scrollY;
      const progress = max > 0 ? Math.min(1, Math.max(0, y / max)) : 0;
      root.style.setProperty("--read-n", (progress * 100).toFixed(2));
      root.style.setProperty("--scroll", `${Math.round(y)}`);
      /* 读到底了：珠子收进环里、环换成深蓝，算一个安静的"读完了" */
      if (progress > 0.995) root.dataset.read = "done";
      else delete root.dataset.read;
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
      root.style.removeProperty("--read-n");
      delete root.dataset.read;
      root.style.removeProperty("--scroll");
    };
  }, []);

  return null;
}