"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

/**
 * 返回键的位置记忆。
 *
 * 为了避免"打开站点先停在页底再滑到页顶"，我们把浏览器的滚动恢复关掉了
 * （`history.scrollRestoration = "manual"`，在 layout 的内联脚本里关，早于浏览器恢复）。
 * 副作用是：按返回键回到上一页时，位置也一起丢了——上一屏明明是读到一半的对话，
 * 回来却落在页顶。这个组件把丢掉的那一半补回来：
 *
 * - 滚动时按路径记下位置（写进 sessionStorage，刷新也拿得到）；
 * - 只有 `popstate`（浏览器返回/前进）才恢复，正常点链接进新页面仍然从顶部开始；
 * - 恢复要试几次：RSC 回来之后先 rAF 一次，内容撑开高度后再补，否则会在
 *   内容还没排好时把页面钉在半空。
 *
 * 两个"归零假象"必须挡掉，否则记下来的永远是 0：
 * 1. 点链接离开时，window 被归零，而在旧组件卸载前还会收到一次 scroll；
 * 2. 返回时新组件挂载的第一帧就是 0。
 * 前者用"路径必须还是我这一页"挡，后者用一段静默期挡。
 */

const KEY = "sm:scroll";

/* 恢复期间闭嘴的截止时间（performance.now 口径） */
let quietUntil = 0;

function read(): Record<string, number> {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Record<string, number>) : {};
  } catch {
    return {};
  }
}

function write(all: Record<string, number>) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* 无痕模式写不了：退化成"回顶部"，不影响使用 */
  }
}

export function ScrollMemory() {
  const pathname = usePathname();

  useEffect(() => {
    let frame = 0;
    let last = -1;

    function remember() {
      frame = 0;
      /* 已经离开了这一页，或者正处在恢复期：这两次 scroll 都是路由造成的，不是人滚的 */
      if (window.location.pathname !== pathname) return;
      if (performance.now() < quietUntil) return;
      const y = Math.round(window.scrollY);
      if (Math.abs(y - last) < 4) return;
      last = y;
      const all = read();
      all[pathname] = y;
      write(all);
    }

    function schedule() {
      if (!frame) frame = requestAnimationFrame(remember);
    }

    schedule();
    window.addEventListener("scroll", schedule, { passive: true });

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
    };
  }, [pathname]);

  useEffect(() => {
    let timers: Array<ReturnType<typeof setTimeout>> = [];

    function restore() {
      const y = read()[window.location.pathname];
      if (!y) return;
      quietUntil = performance.now() + 1200;
      const jump = () => window.scrollTo({ top: y, behavior: "instant" });
      timers.forEach(clearTimeout);
      /* 三次：RSC 回来、内容撑开、最后兜一次 */
      jump();
      timers = [
        setTimeout(jump, 90),
        setTimeout(jump, 280),
        setTimeout(jump, 560),
      ];
    }

    window.addEventListener("popstate", restore);
    return () => {
      window.removeEventListener("popstate", restore);
      timers.forEach(clearTimeout);
    };
  }, []);

  return null;
}