"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import type { CreateSessionInput } from "@/src/lib/api/types";

export type SelfReport = NonNullable<CreateSessionInput["attempt"]["self_report"]>;

export interface Draft {
  problem: string;
  answer: string;
  work: string;
  stuckAt: string;
  selfReport: SelfReport;
}

export const EMPTY_DRAFT: Draft = {
  problem: "",
  answer: "",
  work: "",
  stuckAt: "",
  selfReport: "unsure",
};

interface ProblemFormProps {
  value: Draft;
  onChange: (next: Draft) => void;
  busy: boolean;
  error: string | null;
  onSubmit: (input: CreateSessionInput) => Promise<void>;
  /** 光标在哪个字段上：左侧树突用它做联动高亮 */
  onFocusField?: (field: string | null) => void;
}

const SAMPLE_PROBLEM =
  "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。";
const SAMPLE_WORK =
  "定义域 x>0。f'(x)=1/x-a，令 f'(x)=0 得 x=1/a。a>0 时，最大值为 f(1/a)=-ln a-1≤0，所以 a≥1/e。";

const SELF_REPORTS: { value: SelfReport; label: string }[] = [
  { value: "wrong", label: "做错了" },
  { value: "unsure", label: "不确定" },
  { value: "correct_but_guessed", label: "对了但有点蒙" },
  { value: "no_idea", label: "完全不会" },
];

/**
 * 文本框跟着内容长高，但**有上限**：中文换行多，固定 rows 会一直出现内滚动条；
 * 可如果不封顶，粘一段长题面就会把整块交题板顶长，两边版面被拉斜。
 * 超过上限就地内滚，板子高度基本不动。
 */
function useAutosize(value: string, max: number) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    node.style.height = "auto";
    const needed = node.scrollHeight;
    node.style.height = `${Math.min(needed, max)}px`;
    node.dataset.clip = needed > max + 1 ? "true" : "false";
  }, [value, max]);

  return ref;
}

export function ProblemForm({
  value,
  onChange,
  busy,
  error,
  onSubmit,
  onFocusField,
}: ProblemFormProps) {
  const [localError, setLocalError] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const submitRef = useRef<HTMLButtonElement>(null);

  const problemRef = useAutosize(value.problem, 150);
  const workRef = useAutosize(value.work, 208);

  const clueCount = [value.problem, value.answer, value.work].filter((item) =>
    item.trim(),
  ).length;

  /* 按钮里那团光跟着指针走：直接写 CSS 变量，不进 state */
  function trackCta(event: ReactPointerEvent<HTMLButtonElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty(
      "--bx",
      `${((event.clientX - rect.left) / rect.width) * 100}%`,
    );
    event.currentTarget.style.setProperty(
      "--by",
      `${((event.clientY - rect.top) / rect.height) * 100}%`,
    );
  }

  function patch(next: Partial<Draft>) {
    onChange({ ...value, ...next });
  }

  function fillSample() {
    onChange({
      problem: SAMPLE_PROBLEM,
      answer: "a≥1/e",
      work: SAMPLE_WORK,
      stuckAt: "令导数为 0 那一步，不确定要不要先管 a 是正是负",
      selfReport: "correct_but_guessed",
    });
    setMore(true);
    setLocalError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);

    if (!value.problem.trim()) {
      setLocalError("先把题目粘进来。");
      return;
    }
    if (!value.answer.trim()) {
      setLocalError("填一个答案；完全不会就写“不会”。");
      return;
    }

    await onSubmit({
      problem: { text: value.problem.trim() },
      attempt: {
        answer: value.answer.trim(),
        work: value.work.trim(),
        stuck_at: value.stuckAt.trim() || undefined,
        self_report: value.selfReport,
      },
      mode: "learning",
    });
  }

  return (
    <form className="sm-form" noValidate onSubmit={handleSubmit}>
      <div className="sm-form-head">
        <span className="sm-lab" style={{ margin: 0 }}>
          交题
        </span>
        <span className="sm-form-count">
          <i aria-hidden="true" className="sm-form-tube">
            <u key={clueCount} style={{ width: `${(clueCount / 3) * 100}%` }} />
          </i>
          线索 <b>{clueCount}</b> / 3
        </span>
      </div>

      <div>
        <div className="sm-f-label" style={{ marginBottom: 8 }}>
          学科 <em>自动识别</em>
        </div>
        <p className="sm-fine" style={{ margin: 0 }}>
          不用选。系统从题面判断数学 / 物理 / 语文；识别不准时会明确说明。
        </p>
      </div>

      <label className="sm-f">
        <span className="sm-f-label">
          题目 <em>必填</em>
        </span>
        <textarea
          id="field-problem"
          onBlur={() => onFocusField?.(null)}
          onChange={(event) => patch({ problem: event.target.value })}
          onFocus={() => onFocusField?.("problem")}
          placeholder="粘贴题目；只有照片的话，把题干敲成一行也行"
          ref={problemRef}
          rows={2}
          value={value.problem}
        />
      </label>

      <label className="sm-f">
        <span className="sm-f-label">
          你的答案 <em>必填</em>
        </span>
        <input
          id="field-answer"
          onBlur={() => onFocusField?.(null)}
          onChange={(event) => patch({ answer: event.target.value })}
          onFocus={() => onFocusField?.("answer")}
          placeholder="例如 a≥1/e；完全不会就写“不会”"
          type="text"
          value={value.answer}
        />
      </label>

      <label className="sm-f">
        <span className="sm-f-label">
          你的过程 <em>最有用，可以不写</em>
        </span>
        <textarea
          id="field-work"
          onBlur={() => onFocusField?.(null)}
          onChange={(event) => patch({ work: event.target.value })}
          onFocus={() => onFocusField?.("work")}
          placeholder="写多少都行。卡住的那一行为什么卡住，比答案有用"
          ref={workRef}
          rows={3}
          value={value.work}
        />
      </label>

      <div>
        <button
          aria-controls="form-more"
          aria-expanded={more}
          className="sm-link sm-link-quiet"
          onClick={() => setMore((open) => !open)}
          type="button"
        >
          {more ? "收起" : "补一句：卡在哪、有几分把握"}
          {value.stuckAt.trim() || value.selfReport !== "unsure" ? " · 已填" : ""}
        </button>

        <div className="sm-more" data-open={more} id="form-more">
          <div className="sm-more-in">
            <div className="sm-more-body">
              <label className="sm-f">
                <span className="sm-f-label">卡在哪</span>
                <input
                  id="field-stuck"
                  onBlur={() => onFocusField?.(null)}
                  onChange={(event) => patch({ stuckAt: event.target.value })}
                  onFocus={() => onFocusField?.("stuck")}
                  placeholder="一句话就行，例如：写到求导就不确定要不要分类"
                  type="text"
                  value={value.stuckAt}
                />
              </label>

              <div>
                <div className="sm-f-label" style={{ marginBottom: 8 }}>
                  这题你有几成把握
                </div>
                <div aria-label="这题你有几成把握" className="sm-picks" role="radiogroup">
                  {SELF_REPORTS.map((item) => (
                    <label className="sm-pick" key={item.value}>
                      <input
                        checked={value.selfReport === item.value}
                        name="self-report"
                        onChange={() => patch({ selfReport: item.value })}
                        type="radio"
                        value={item.value}
                      />
                      <span>{item.label}</span>
                    </label>
                  ))}
                </div>
                <p className="sm-note sm-note-quiet" style={{ marginTop: 10 }}>
                  只用来区分真会和蒙对。
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {localError ?? error ? (
        <p className="sm-alert" role="alert">
          {localError ?? error}
        </p>
      ) : null}

      <div className="sm-form-foot">
        <button className="sm-cta" disabled={busy} onPointerMove={trackCta} ref={submitRef} type="submit">
          {busy ? "正在拆题" : "开始拆题"}
          <span aria-hidden="true" className="sm-ar">
            →
          </span>
        </button>
        <button className="sm-link" disabled={busy} onClick={fillSample} type="button">
          没有题目？填入示例题
        </button>
      </div>

      {busy ? (
        <p className="sm-busy" role="status">
          <i />
          <i />
          <i />
          正在读你的过程，不打断你
        </p>
      ) : null}

      <p className="sm-fine" style={{ marginTop: 0 }}>
        数学走已标注的种子题；物理与语文现场建图，需要服务端配置模型 key。
        语文按“只给结构提示”承诺：不追问、不判断卡点。前 3 轮不给最终答案。
      </p>
    </form>
  );
}