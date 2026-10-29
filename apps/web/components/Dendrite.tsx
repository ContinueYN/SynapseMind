/**
 * 树突：一句话的进度语法。
 *
 * 交题页用它数“手上有几条线索”，诊断页用它记“问到第几层”。
 * 同一形状在两处出现，用户不用重新学一遍——这是“连续”的来源，不是装饰。
 *
 * 坐标全部由序号算出，没有随机数：服务端渲染和客户端必须画出同一条线。
 */

export type DendriteState = "done" | "active" | "todo" | "stuck";

export interface DendriteStop {
  id: string;
  label: string;
  detail?: string;
  state: DendriteState;
  /** 提示轮：路径退回一级，枝干向左让一下 */
  hint?: boolean;
  /** 指针停在别处的某一行上：这一格跟着亮 */
  hot?: boolean;
}

interface DendriteProps {
  stops: DendriteStop[];
  /** 相邻两点的纵向间距 */
  step?: number;
  pad?: number;
}

const SPINE_X = 24;

function xAt(index: number, hint: boolean) {
  if (hint) return 10;
  return SPINE_X + (index % 2 === 0 ? -3 : 3);
}

function segment(x0: number, y0: number, x1: number, y1: number, bend: boolean) {
  const mid = (y0 + y1) / 2;
  const bow = bend ? -14 : 0;
  return `M${x0} ${y0} C${x0 + bow} ${mid} ${x1} ${mid} ${x1} ${y1}`;
}

export function Dendrite({ stops, step = 58, pad = 14 }: DendriteProps) {
  if (stops.length === 0) return null;

  const height = pad * 2 + (stops.length - 1) * step;
  const ys = stops.map((_, index) => pad + index * step);
  const xs = stops.map((stop, index) => xAt(index, Boolean(stop.hint)));

  return (
    <div className="sm-dendrite" style={{ height }}>
      <svg
        aria-hidden="true"
        height={height}
        preserveAspectRatio="none"
        viewBox={`0 0 44 ${height}`}
        width={44}
      >
        {stops.slice(1).map((stop, index) => {
          const from = index;
          const to = index + 1;
          return (
            <path
              className="sm-d-seg"
              d={segment(xs[from], ys[from], xs[to], ys[to], Boolean(stop.hint))}
              data-state={stop.state}
              key={`seg-${stop.id}`}
            />
          );
        })}

        {stops.map((stop, index) => (
          <g
            className="sm-d-node"
            data-hot={stop.hot ? "true" : undefined}
            data-state={stop.state}
            key={stop.id}
            transform={`translate(${xs[index]} ${ys[index]})`}
          >
            {stop.state === "active" || stop.state === "stuck" ? (
              <circle className="sm-d-halo" r={stop.state === "stuck" ? 11 : 9} />
            ) : null}
            <circle className="sm-d-dot" r={stop.state === "stuck" ? 4.4 : 3.4} />
            {stop.state === "stuck" ? (
              <g className="sm-d-spur">
                <path d="M2 -8 L8 -13" />
                <path d="M4 2 L10 5" />
                <path d="M-3 -8 L-8 -11" />
              </g>
            ) : null}
          </g>
        ))}
      </svg>

      <ol className="sm-d-labels">
        {stops.map((stop, index) => (
          <li
            aria-current={stop.state === "active" ? "step" : undefined}
            className="sm-d-label"
            data-hot={stop.hot ? "true" : undefined}
            data-state={stop.state}
            key={stop.id}
            style={{ top: ys[index] }}
          >
            <b>{stop.label}</b>
            {stop.detail ? <small>{stop.detail}</small> : null}
          </li>
        ))}
      </ol>
    </div>
  );
}