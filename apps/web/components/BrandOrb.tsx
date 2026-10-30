"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * 顶部那颗球。
 *
 * 中间是网站图案，外面一圈是阅读进度（`--read-n`，由 ScrollRule 写），
 * 指针放上去才展开成一条——展开的是宽度，球本身不动，所以那圈进度始终围着图案。
 *
 * 为什么不像原来那样做一条横贯全宽的玻璃条：它一直在占地方，把视线从内容上拉走，
 * 页面还矮了一截。一颗 54px 的球既在，又不抢。
 */
export function BrandOrb() {
  const pathname = usePathname();
  const onHome = pathname === "/";

  return (
    <div className="sm-orb-hang">
      <Link
        aria-label={onHome ? "SynapseMind" : "回到首页"}
        className="sm-orb"
        href="/"
      >
        <span aria-hidden="true" className="sm-orb-face">
          <svg className="sm-mark" fill="none" viewBox="0 0 24 24">
            <path
              className="sm-mark-link"
              d="M5.5 17.5 12 12l6.5-5.5"
              stroke="currentColor"
              strokeLinecap="round"
              strokeWidth="1.2"
            />
            <circle cx="5.5" cy="17.5" fill="currentColor" r="1.9" />
            <circle cx="18.5" cy="6.5" fill="currentColor" r="1.9" />
            <circle
              className="sm-mark-pulse"
              cx="12"
              cy="12"
              r="2.8"
              stroke="currentColor"
              strokeWidth="0.9"
            />
          </svg>
        </span>

        {/* 进度环：pathLength=100 把周长归一成 100，dashoffset 就等于"还剩多少" */}
        <span aria-hidden="true" className="sm-orb-ring">
          <svg viewBox="0 0 44 44">
            <circle className="sm-orb-track" cx="22" cy="22" r="20" />
            <circle
              className="sm-orb-fill"
              cx="22"
              cy="22"
              pathLength={100}
              r="20"
            />
            {/* 环头那颗珠：从 3 点钟出发，被 svg 的 -90° 转到 12 点，再按进度转 */}
            <g className="sm-orb-spark">
              <circle cx="42" cy="22" r="1.9" />
            </g>
          </svg>
        </span>

        <span className="sm-orb-words">
          <b>SynapseMind</b>
          <em>{onHome ? "单题诊断" : "回首页"}</em>
        </span>
      </Link>
    </div>
  );
}