import type { ReactNode } from "react";

/**
 * 路由级外壳：每次换页重新挂载，所以这一层动画只在导航时跑一次。
 * 页面内部的动画归各组件自己管。
 *
 * 换页的那层水（`.sm-transit`）在 AppShell 里挂，不放这里：
 * 这一层的入场动画带 translate 与 blur，会把 fixed 子元素变成相对整页定位。
 */
export default function Template({ children }: { children: ReactNode }) {
  return <div className="sm-page">{children}</div>;
}