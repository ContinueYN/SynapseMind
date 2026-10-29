"use client";

import { usePathname } from "next/navigation";

/**
 * 换页时从顶上淌下去的一层水。
 *
 * 放在 AppShell 里、`.sm-page` 外面：
 * `.sm-page` 入场时有 `translate` 与 `filter: blur()`，这两个都会让它成为
 * fixed 子元素的包含块——放里面的话，这层水会按整页高度铺，而不是按视口铺。
 *
 * `key={pathname}` 让它每次换页重新挂载，动画就重新跑一遍。
 */
export function Transit() {
  const pathname = usePathname();

  return <span aria-hidden="true" className="sm-transit" key={pathname} />;
}