interface ProgressRailProps {
  turn: number;
  maxTurns: number;
  confidence: number;
  topHypothesis: string;
}

export function ProgressRail({
  turn,
  maxTurns,
  confidence,
  topHypothesis,
}: ProgressRailProps) {
  const percent = Math.round(confidence * 100);
  return (
    <section className="progress-rail" aria-label="诊断进度">
      <div className="progress-copy">
        <span>
          第 {Math.min(turn + 1, maxTurns)} / {maxTurns} 轮
        </span>
        <span className="muted">当前假设：{topHypothesis}</span>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label="当前假设置信度"
      >
        <span style={{ width: `${Math.max(4, percent)}%` }} />
      </div>
      <span className="progress-value">{percent}%</span>
    </section>
  );
}