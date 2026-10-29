const PHASES = ["交题", "拆题", "追问", "定位"] as const;

const PHASE_BY_STATE: Record<string, number> = {
  INGEST: 0,
  PARSE: 0,
  NEED_INPUT: 0,
  ALIGN: 1,
  PROBE: 2,
  DIAGNOSE: 3,
  INTERVENE: 3,
  VERIFY: 3,
  STOP: 3,
  CLOSED: 3,
};

/**
 * 四段通路：显示诊断走到哪一段。
 * 注意这不是"这题分几步"——解法图数据没有暴露给前端，不能编。
 */
export function ProgressRail({ state }: { state: string }) {
  const active = PHASE_BY_STATE[state] ?? 0;

  return (
    <ol aria-label="诊断进度" className="sm-steps">
      {PHASES.map((label, index) => (
        <li
          className="sm-step"
          data-state={index < active ? "done" : index === active ? "active" : undefined}
          key={label}
        >
          <span aria-hidden="true" className="sm-step-n">
            {index + 1}
          </span>
          <span>{label}</span>
        </li>
      ))}
    </ol>
  );
}