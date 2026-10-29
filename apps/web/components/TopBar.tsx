"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * 顶栏右侧：模式 + 一键回首页。
 * 只在非首页出现——首页上它没有意义，摆着就是装饰。
 */
export function TopBar() {
  const pathname = usePathname();
  const onHome = pathname === "/";

  return (
    <div className="sm-top-meta">
      <span className="sm-mode">
        <span aria-hidden="true" className="sm-dot" />
        学习模式
      </span>

      {onHome ? null : (
        <Link className="sm-home-link" href="/">
          <span aria-hidden="true" className="sm-home-ar">
            ←
          </span>
          回到首页
        </Link>
      )}
    </div>
  );
}