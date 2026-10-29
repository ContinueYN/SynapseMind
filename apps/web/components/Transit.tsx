"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * 换页时从左侧掠过的那两道斜光。
 *
 * 放在 AppShell 里、`.sm-page` 外面：
 * `.sm-page` 入场时有 `translate` 与 `filter: blur()`，这两个都会让它成为
 * fixed 子元素的包含块——放里面的话，这层光会按整页高度铺，而不是按视口铺。
 *
 * 动画由 `data-run` 触发，而不是跟着元素挂载就走：
 * 开发模式下 CSS 由 JS 注入，挂载时样式可能还没到，动画会白白跑在"样式到达之前"，
 * 于是换页时光是迟到半秒才出现的。先渲染成静止的一帧，effect 里再打开——两种模式都对。
 */
export function Transit() {
  const pathname = usePathname();
  const [run, setRun] = useState(false);

  useEffect(() => {
    setRun(true);
  }, [pathname]);

  return (
    <span
      aria-hidden="true"
      className="sm-transit"
      data-run={run ? "true" : "false"}
      key={pathname}
    />
  );
}