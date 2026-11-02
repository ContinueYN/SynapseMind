"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

interface RevealProps {
  children: ReactNode;
  className?: string;
  id?: string;
}

/**
 * 段落入场的边界：进入视口的那一段才动，已经读过的不再动。
 *
 * 首屏的段落一开始就是可见的（IntersectionObserver 第一帧就报 intersecting），
 * 所以 SSR 出去的内容永远不会被藏起来；只有**在视口外**的段落会被压住等一下。
 */
export function Reveal({ children, className = "", id }: RevealProps) {
  const ref = useRef<HTMLElement | null>(null);
  /* null = 还不知道（服务端/首帧）；true/false = 观察结果 */
  const [seen, setSeen] = useState<boolean | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setSeen(true);
            observer.disconnect();
          } else {
            setSeen(false);
          }
        }
      },
      { rootMargin: "0px 0px -14% 0px", threshold: 0.12 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <section
      className={className}
      data-in={seen === null ? undefined : seen ? "true" : "false"}
      id={id}
      ref={ref}
    >
      {children}
    </section>
  );
}