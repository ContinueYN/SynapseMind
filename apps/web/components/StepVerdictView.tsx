import type { StepVerdict } from "@/src/lib/api/types";

export interface VerdictCopy {
  tag: string;
  badge: string;
  caveat: string;
}

interface StepVerdictViewProps {
  verdict: StepVerdict;
  copy: Record<StepVerdict["status"], VerdictCopy>;
}

/**
 * One verification result, shared by the math and physics step checks.
 *
 * The status wording is supplied by each subject: math can say "这个等号不
 * 成立", physics must not. ``findings`` is math-only today, so physics falls
 * back to the server's free-text ``detail``.
 */
export function StepVerdictView({ verdict, copy }: StepVerdictViewProps) {
  const text = copy[verdict.status];

  return (
    <div
      aria-live="polite"
      className="sm-stepcheck-result"
      data-status={verdict.status}
      role="status"
    >
      <div className="sm-stepcheck-result-head">
        <b>{text.tag}</b>
        <span>{text.badge}</span>
      </div>
      {verdict.findings && verdict.findings.length > 0 ? (
        <ul className="sm-stepcheck-findings">
          {verdict.findings.map((finding, index) => (
            <li key={`${finding.kind}-${finding.left}-${finding.right}-${index}`}>
              <code>
                {finding.left} = {finding.right}
              </code>
              <span>{finding.summary}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p>{verdict.detail}</p>
      )}
      <p className="sm-stepcheck-caveat">{text.caveat}</p>
    </div>
  );
}