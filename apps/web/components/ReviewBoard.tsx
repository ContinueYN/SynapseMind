"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Plane } from "@/components/Plane";
import {
  REVIEW_JUDGMENTS,
  buildReviewCsv,
  downloadReviewCsv,
  loadReviewDrafts,
  reviewCsvFilename,
  saveReviewDrafts,
  type ReviewDraft,
  type ReviewDrafts,
} from "@/components/review-sheet";
import { API_BASE, listReviewItems } from "@/src/lib/api/client";
import type { ReviewItem } from "@/src/lib/api/types";

/**
 * 教师复核页。
 *
 * 只做三件事：读队列、逐条标记、导出 CSV。队列是只读的，判断存在本机
 * 浏览器里，不写回复核库；服务端没有鉴权，所以这一页是本机工具，不是
 * 面向学生的入口。
 */

const EMPTY_DRAFT: ReviewDraft = { judgment: "", note: "" };

function formatCreatedAt(value: string): string {
  const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  if (!match) return value;
  const utc = value.endsWith("Z") || value.endsWith("+00:00");
  return `${match[1]} ${match[2]}${utc ? " UTC" : ""}`;
}

function confidenceLabel(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function ReviewBoard() {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [drafts, setDrafts] = useState<ReviewDrafts>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [exported, setExported] = useState<string | null>(null);

  useEffect(() => {
    setDrafts(loadReviewDrafts(window.localStorage));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError(null);
    listReviewItems()
      .then((listing) => {
        if (!cancelled) setItems(listing.items ?? []);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "读取复核队列失败。");
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const judged = (items ?? []).filter(
    (item) => drafts[item.session_id]?.judgment,
  ).length;

  function updateDraft(sessionId: string, patch: Partial<ReviewDraft>) {
    const current = drafts[sessionId] ?? EMPTY_DRAFT;
    const next = { ...current, ...patch };
    const updated = { ...drafts };
    if (!next.judgment && !next.note.trim()) {
      delete updated[sessionId];
    } else {
      updated[sessionId] = next;
    }
    setDrafts(updated);
    saveReviewDrafts(window.localStorage, updated);
    setExported(null);
  }

  function clearJudgments() {
    setDrafts({});
    saveReviewDrafts(window.localStorage, {});
    setExported(null);
  }

  function exportCsv() {
    if (!items || items.length === 0) return;
    downloadReviewCsv(buildReviewCsv(items, drafts), reviewCsvFilename());
    setExported(`已导出 ${items.length} 条，其中 ${judged} 条带人工判断。`);
  }

  if (error && items === null) {
    return (
      <section className="sm-review">
        <Plane className="sm-review-hero">
          <p className="sm-kicker">复核队列没打开</p>
          <h1 className="sm-h1">{error}</h1>
          <p className="sm-p">
            复核服务没有响应。请确认 API 已启动（{API_BASE}），再重试。
          </p>
          <p className="sm-review-actions">
            <button
              className="sm-cta"
              onClick={() => {
                setReload((value) => value + 1);
              }}
              type="button"
            >
              重试
              <span aria-hidden="true" className="sm-ar">
                →
              </span>
            </button>
          </p>
          <p className="sm-fine">
            <Link href="/">← 回到交题页</Link>
          </p>
        </Plane>
      </section>
    );
  }

  if (items === null) {
    return (
      <section className="sm-review">
        <Plane className="sm-review-hero">
          <p className="sm-eyebrow">
            <span aria-hidden="true" className="sm-dot" />
            教师复核 · 本机工具
          </p>
          <h1 className="sm-h1">正在读异议队列。</h1>
          <p className="sm-p">只读；不会改动任何会话或卡点卡。</p>
        </Plane>
      </section>
    );
  }

  return (
    <div className="sm-review">
      <Plane className="sm-review-hero">
        <p className="sm-eyebrow">
          <span aria-hidden="true" className="sm-dot" />
          教师复核 · 本机工具
        </p>

        <h1 className="sm-h1">只看卡面，不看原文。</h1>
        <p className="sm-lede">
          学生点「我不同意」后，队列只记下那张卡的结论与位置。这里可以逐条判断，
          再把人工判断导出成 CSV；判断本身不写回复核库。
        </p>

        <div className="sm-review-stats" aria-label="队列概况" role="group">
          <div>
            <b>{items.length}</b>
            <span>条异议</span>
          </div>
          <div>
            <b>{judged}</b>
            <span>已判断</span>
          </div>
          <div>
            <b>{items.length - judged}</b>
            <span>待判断</span>
          </div>
        </div>

        <div className="sm-review-actions">
          <button
            className="sm-cta"
            disabled={items.length === 0}
            onClick={exportCsv}
            type="button"
          >
            导出 CSV
            <span aria-hidden="true" className="sm-ar">
              →
            </span>
          </button>
          <button
            className="sm-review-btn"
            disabled={busy}
            onClick={() => {
              setReload((value) => value + 1);
            }}
            type="button"
          >
            {busy ? "正在刷新…" : "刷新队列"}
          </button>
          {judged > 0 ? (
            <button
              className="sm-review-btn sm-review-btn--quiet"
              onClick={clearJudgments}
              type="button"
            >
              清空判断
            </button>
          ) : null}
        </div>

        {exported ? (
          <p className="sm-review-exported" role="status">
            {exported}
          </p>
        ) : null}

        <p className="sm-fine">
          队列不含学生原文；「备注」也只留在这台浏览器里。换机器、清站点数据都会丢，
          需要留档就导出 CSV。
        </p>
      </Plane>

      {error ? (
        <p className="sm-alert sm-review-alert" role="alert">
          {error}
        </p>
      ) : null}

      {items.length === 0 ? (
        <Plane className="sm-review-empty">
          <h2 className="sm-h2">还没有异议记录。</h2>
          <p className="sm-p">
            学生点过「我不同意」的卡会出现在这里。现在队列是空的，不需要处理。
          </p>
          <p className="sm-fine">
            <Link href="/">← 回到交题页</Link>
          </p>
        </Plane>
      ) : (
        <section aria-label="异议队列" className="sm-review-queue">
          <div className="sm-review-queue-head">
            <p className="sm-kicker">待复核</p>
            <p>
              按时间倒序；一行一张卡。判断只标在本地，导出后交给教研或归档。
            </p>
          </div>

          <ol className="sm-review-list">
            {items.map((item) => {
              const draft = drafts[item.session_id] ?? EMPTY_DRAFT;
              return (
                <li className="sm-tile sm-review-item" key={item.session_id}>
                  <header className="sm-review-item-head">
                    <span className="sm-review-layer">{item.layer}</span>
                    <span className="sm-review-time" title={item.created_at}>
                      {formatCreatedAt(item.created_at)}
                    </span>
                    <span className="sm-review-confidence">
                      把握 {confidenceLabel(item.confidence)}
                    </span>
                  </header>

                  <p className="sm-review-title">{item.label}</p>
                  <p className="sm-review-line">{item.one_line}</p>

                  <p className="sm-review-meta">
                    <span>{item.problem_id}</span>
                    <span>{item.node_id}</span>
                    <code>{item.session_id}</code>
                  </p>

                  <div className="sm-review-judge">
                    <div
                      aria-label={`${item.session_id} 的人工判断`}
                      className="sm-review-choices"
                      role="group"
                    >
                      {REVIEW_JUDGMENTS.map((option) => (
                        <button
                          aria-pressed={draft.judgment === option.value}
                          className="sm-review-choice"
                          key={option.value}
                          onClick={() => {
                            updateDraft(item.session_id, {
                              judgment:
                                draft.judgment === option.value ? "" : option.value,
                            });
                          }}
                          type="button"
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>

                    <label className="sm-f sm-review-note">
                      <span className="sm-f-label">
                        备注
                        <em>可选</em>
                      </span>
                      <input
                        aria-label={`${item.session_id} 的备注`}
                        maxLength={500}
                        onChange={(event) => {
                          updateDraft(item.session_id, { note: event.target.value });
                        }}
                        placeholder="例如：卡面把定义域那一步说错了"
                        value={draft.note}
                      />
                    </label>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </div>
  );
}