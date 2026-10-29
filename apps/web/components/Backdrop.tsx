"use client";

import { useEffect } from "react";

/**
 * 背景层：四团冰蓝光斑。
 * 玻璃得有东西可折射——没有它，毛玻璃只是一块灰色。
 */
export function Backdrop() {
  useEffect(() => {
    const blobs = Array.from(document.querySelectorAll<HTMLElement>(".sm-blob"));
    if (blobs.length === 0) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let tx = 0;
    let ty = 0;
    let cx = 0;
    let cy = 0;
    let raf = 0;

    function onMove(event: PointerEvent) {
      tx = (event.clientX / window.innerWidth - 0.5) * -30;
      ty = (event.clientY / window.innerHeight - 0.5) * -22;
    }

    function loop() {
      cx += (tx - cx) * 0.04;
      cy += (ty - cy) * 0.04;
      blobs.forEach((blob, index) => {
        const k = ((index % 3) + 1) * 0.6;
        blob.style.transform = `translate3d(${(cx * k).toFixed(2)}px, ${(cy * k).toFixed(2)}px, 0)`;
      });
      raf = requestAnimationFrame(loop);
    }

    if (reduced) return;

    window.addEventListener("pointermove", onMove, { passive: true });
    raf = requestAnimationFrame(loop);

    return () => {
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div aria-hidden="true" className="sm-bg">
      <div className="sm-blob sm-blob-1" />
      <div className="sm-blob sm-blob-2" />
      <div className="sm-blob sm-blob-3" />
      <div className="sm-blob sm-blob-4" />
    </div>
  );
}