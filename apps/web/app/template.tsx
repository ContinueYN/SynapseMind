import type { ReactNode } from "react";

/**
 * 路由级外壳：每次换页重新挂载，所以这一层动画只在导航时跑一次。
 * 页面内部的动画归各组件自己管。
 */
export default function Template({ children }: { children: ReactNode }) {
  return <div className="sm-page">{children}</div>;
}