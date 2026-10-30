import type { ReactNode } from "react";

/**
 * 路由级外壳：每次换页重新挂载。
 *
 * 这里**不做**任何过场（不盖、不扫、不整屏位移）——换页的观感由页面内部
 * 各组件的入位交代：首页两块板错开 90ms 浮上来，追问页左栏先到、主栏后到。
 * 这一层只管把 children 包起来。
 */
export default function Template({ children }: { children: ReactNode }) {
  return <div className="sm-page">{children}</div>;
}