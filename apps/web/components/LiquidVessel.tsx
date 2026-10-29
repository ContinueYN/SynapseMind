"use client";

import { useEffect, useId, useRef } from "react";

/**
 * 液面：容器里的水是真的在算（每帧重写 SVG 路径）。
 *
 * 物理三条：
 *   1. 液面高度 = 走过的轮次 / 总轮次，弹簧式上升，不到最后一轮不会到顶
 *   2. 推容器 → 液面倾斜，倾角跟手的横向速度成正比，松手按阻尼平复
 *   3. 点水面 → 涟漪从落点扩散（高斯 × 正弦），不是从中间冒泡
 */

const X0 = 14;
const W = 176;
const TOP = 16;
const BOT = 284;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

interface LiquidVesselProps {
  turn: number;
  maxTurns: number;
}

export function LiquidVessel({ turn, maxTurns }: LiquidVesselProps) {
  const uid = useId().replace(/[:]/g, "");
  const rootRef = useRef<HTMLDivElement>(null);
  const waveRef = useRef<SVGPathElement>(null);
  const sheenRef = useRef<SVGPathElement>(null);
  const poolRef = useRef<HTMLSpanElement>(null);

  const state = useRef({
    level: 0.12,
    target: 0.12,
    slope: 0,
    slopeTarget: 0,
    phase: 0,
    pulse: 0,
    pulsePos: 0.5,
    pulsePhase: 0,
    dragging: false,
    lastX: 0,
    lastT: 0,
  });

  const rounds = Math.max(1, Math.round(maxTurns || 6));

  useEffect(() => {
    const next = clamp(turn / Math.max(1, maxTurns), 0.12, 0.96);
    state.current.target = next;
    state.current.pulse = 6.5;
    state.current.pulsePhase = 0;
  }, [turn, maxTurns]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;

    function draw() {
      const s = state.current;
      const wave = waveRef.current;
      const sheen = sheenRef.current;
      if (!wave) return;

      const baseY = BOT - (BOT - TOP) * s.level;
      const steps = 26;
      const points: string[] = [];

      for (let i = 0; i <= steps; i += 1) {
        const f = i / steps;
        const x = X0 + W * f;
        const y =
          baseY +
          s.slope * (f - 0.5) * 26 +
          Math.sin(s.phase + f * 7) * 2.1 +
          s.pulse * Math.exp(-Math.abs(f - s.pulsePos) / 0.16) * Math.sin(s.pulsePhase + f * 14);
        points.push(`${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`);
      }

      wave.setAttribute("d", `${points.join(" ")} L${X0 + W} ${BOT} L${X0} ${BOT} Z`);

      if (sheen) {
        const line = points.join(" ");
        sheen.setAttribute(
          "d",
          `${line} L${X0 + W} ${(baseY + 13).toFixed(1)} L${X0} ${(baseY + 13).toFixed(1)} Z`,
        );
      }

      if (poolRef.current) {
        poolRef.current.style.transform = `translateX(${(s.slope * 14).toFixed(1)}px)`;
      }
    }

    function loop() {
      const s = state.current;
      s.phase += 0.05;
      s.slope += (s.slopeTarget - s.slope) * 0.18;
      if (!s.dragging) s.slopeTarget *= 0.9;
      s.pulse *= 0.93;
      s.pulsePhase += 0.35;
      s.level += (s.target - s.level) * 0.05;
      draw();
      raf = requestAnimationFrame(loop);
    }

    if (reduced) {
      draw();
      return;
    }

    raf = requestAnimationFrame(loop);

    function onDown(event: PointerEvent) {
      const s = state.current;
      s.dragging = true;
      s.lastX = event.clientX;
      s.lastT = performance.now();
      root?.setPointerCapture?.(event.pointerId);
    }

    function onMove(event: PointerEvent) {
      const s = state.current;
      if (!s.dragging) return;
      const now = performance.now();
      const dt = Math.max(8, now - s.lastT);
      const v = (event.clientX - s.lastX) / dt;
      s.slopeTarget = clamp(v * 26, -1.7, 1.7);
      s.lastX = event.clientX;
      s.lastT = now;
    }

    function onUp() {
      state.current.dragging = false;
      state.current.slopeTarget = 0;
    }

    function onTap(event: PointerEvent) {
      const rect = root?.getBoundingClientRect();
      if (!rect) return;
      const s = state.current;
      s.pulsePos = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      s.pulse = 7.5;
      s.pulsePhase = 0;
    }

    root.addEventListener("pointerdown", onDown);
    root.addEventListener("pointermove", onMove);
    root.addEventListener("pointerup", onUp);
    root.addEventListener("pointercancel", onUp);
    root.addEventListener("click", onTap);

    return () => {
      cancelAnimationFrame(raf);
      root.removeEventListener("pointerdown", onDown);
      root.removeEventListener("pointermove", onMove);
      root.removeEventListener("pointerup", onUp);
      root.removeEventListener("pointercancel", onUp);
      root.removeEventListener("click", onTap);
    };
  }, []);

  return (
    <div
      aria-label={`诊断进度：第 ${turn} 轮，共 ${maxTurns} 轮`}
      className="sm-vessel"
      ref={rootRef}
      role="img"
    >
      <span aria-hidden="true" className="sm-vessel-pool" ref={poolRef} />
      <svg viewBox="0 0 250 300">
        <defs>
          <clipPath id={`ves-${uid}`}>
            <rect height="268" rx="30" width={W} x={X0} y={TOP} />
          </clipPath>
          <linearGradient id={`liq-${uid}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#d6eefa" />
            <stop offset="45%" stopColor="#a2d0e9" />
            <stop offset="100%" stopColor="#66a8ce" />
          </linearGradient>
          <linearGradient id={`rim-${uid}`} x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#ffffff" />
            <stop offset="52%" stopColor="rgba(255,255,255,0.5)" />
            <stop offset="100%" stopColor="rgba(255,255,255,0.96)" />
          </linearGradient>
        </defs>

        <g clipPath={`url(#ves-${uid})`}>
          <rect fill="rgba(255,255,255,0.3)" height="268" width={W} x={X0} y={TOP} />
          <path d={`M${X0} 250 L${X0 + W} 250 L${X0 + W} 284 L${X0} 284 Z`} fill={`url(#liq-${uid})`} ref={waveRef} />
          <path d={`M${X0} 250 L${X0 + W} 250 L${X0 + W} 262 L${X0} 262 Z`} fill="rgba(255,255,255,0.32)" ref={sheenRef} />
          <ellipse cx="102" cy="150" fill="rgba(255,255,255,0.13)" rx="92" ry="122" />
        </g>

        <rect
          fill="none"
          height="268"
          rx="30"
          stroke={`url(#rim-${uid})`}
          strokeWidth="1.8"
          width={W}
          x={X0}
          y={TOP}
        />
        <rect fill="rgba(255,255,255,0.24)" height="56" rx="21" width="164" x="20" y="22" />

        {Array.from({ length: rounds }, (_, index) => {
          const k = index + 1;
          const y = BOT - (BOT - TOP - 26) * (k / rounds) - 8;
          const on = k <= turn;
          return (
            <g key={k}>
              <line className="sm-tick" data-on={on} x1="198" x2="212" y1={y} y2={y} />
              <text className="sm-tnum" data-on={on} x="216" y={y + 3}>
                {k}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}