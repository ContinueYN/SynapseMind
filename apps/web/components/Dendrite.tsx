/**
 * 进度柱：一句话的进度语法。
 *
 * 交题页用它数"手上有几条线索"，诊断页用它记"问到第几层"。
 * 同一形状在两处出现，用户不用重新学一遍——这是"连续"的来源，不是装饰。
 *
 * 画法：一根玻璃管 + 液面。走过的部分被蓝填满，液面停在当前这一格；
 * 节点是一颗玻璃珠，不是折线——上一版的曲线与"卡点"三根短须在 22px 宽里
 * 糊成一团（用户原话：卡点线不好看），所以这版只用两种东西：一根管、几颗珠。
 */

import type { CSSProperties } from "react";

export type DendriteState = "done" | "active" | "todo" | "stuck";

export interface DendriteStop {
  id: string;
  label: string;
  detail?: string;
  state: DendriteState;
  /** 提示轮：路径退回一级，标签前加一个"退"字 */
  hint?: boolean;
  /** 指针停在别处的某一行上：这一格跟着亮 */
  hot?: boolean;
}

interface DendriteProps {
  stops: DendriteStop[];
  /** 相邻两点的纵向间距 */
  step?: number;
}

/** 液面停在"你正在这一格"：优先 active/stuck，否则停在最后一个已完成的格子 */
function fillIndex(stops: DendriteStop[]) {
  const current = stops.findIndex((stop) => stop.state === "active" || stop.state === "stuck");
  if (current >= 0) return current;
  let last = -1;
  stops.forEach((stop, index) => {
    if (stop.state === "done") last = index;
  });
  return Math.max(0, last);
}

export function Dendrite({ stops, step = 58 }: DendriteProps) {
  if (stops.length === 0) return null;

  const ratio = stops.length > 1 ? fillIndex(stops) / (stops.length - 1) : 1;
  const fill = `${Math.round(ratio * 100)}%`;

  return (
    <div className="sm-col" style={{ "--col-fill": fill, "--col-step": `${step}px` } as CSSProperties}>
      <span aria-hidden="true" className="sm-col-tube">
        <i />
      </span>

      <ol className="sm-col-rows">
        {stops.map((stop) => (
          <li
            aria-current={stop.state === "active" ? "step" : undefined}
            className="sm-col-row"
            data-hot={stop.hot ? "true" : undefined}
            data-state={stop.state}
            key={stop.id}
          >
            <span aria-hidden="true" className="sm-col-bead" />
            <span className="sm-col-txt">
              <b>
                {stop.hint ? <em className="sm-col-hint">退</em> : null}
                {stop.label}
              </b>
              {stop.detail ? <small>{stop.detail}</small> : null}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}