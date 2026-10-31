"""Knowledge retrieval evaluation for the optional RAG side path.

Scores a fixed concept-label query set against the checked-in corpus with the
real local embedding model (FastEmbed + BAAI/bge-small-zh-v1.5) and writes a
reproducible markdown report.

    python scripts/eval/knowledge_retrieval.py --check   # no model, validate data
    python scripts/eval/knowledge_retrieval.py           # needs the model cache

The script never starts the API and never sees student prose: every query is a
concept label, exactly like the labels the UI sends. The ``SYNAPSE_RAG`` switch
only controls whether the API builds this retriever; the evaluation constructs
the same corpus, embedder and index directly so it can also score below the
production threshold. ``SYNAPSE_RAG_MIN_SCORE`` (or ``--min-score``) sets the
threshold under test; the report also sweeps nearby thresholds.

Exit codes: 0 gate passed, 1 gate failed, 2 setup error (model, corpus or query
set unusable). Retuning the corpus or a query should be followed by a rerun;
the report records both input hashes so a number can be traced to its inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import synapse.infrastructure.knowledge as knowledge_package  # noqa: E402
from synapse.application.knowledge import KnowledgeUnavailable  # noqa: E402
from synapse.infrastructure.knowledge.builder import (  # noqa: E402
    DEFAULT_MIN_SCORE,
    KnowledgeSettings,
)
from synapse.infrastructure.knowledge.corpus import DEFAULT_CORPUS, load_corpus  # noqa: E402
from synapse.infrastructure.knowledge.embedding import FastEmbedEmbedder  # noqa: E402
from synapse.infrastructure.knowledge.index import InMemoryKnowledgeIndex  # noqa: E402

DEFAULT_QUERIES = ROOT / "scripts" / "eval" / "data" / "knowledge-queries-v0.1.jsonl"
DEFAULT_OUT = ROOT / "eval" / "reports" / "knowledge-retrieval-v0.1.md"
SWEEP = (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65)
TOP_K = 3
# Top-1 is allowed a small sibling-card slack; finding the concept somewhere in
# the top 3 is not. These bars are deliberately explicit so a regression is a
# failed run, not a number someone has to interpret.
TOP1_GATE = 0.90
MAX_SAMPLE = 8
_KINDS = frozenset({"relevant", "filter", "irrelevant"})
_SUBJECTS = frozenset({"math", "physics"})


@dataclass(frozen=True, slots=True)
class Query:
    id: str
    kind: str
    text: str
    subject: str | None
    expect: tuple[str, ...]
    forbid: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Scored:
    """One query plus its full ranking (fetched without a threshold)."""

    query: Query
    hits: tuple  # tuple[KnowledgeHit, ...]


@dataclass(frozen=True, slots=True)
class Outcome:
    query: Query
    hits: tuple  # tuple[KnowledgeHit, ...]
    kept: tuple  # hits that survive the threshold (and subject filter)
    rank: int | None
    top1_ok: bool
    top3_ok: bool
    ok: bool


def _reject_unknown_fields(raw: dict, allowed: set[str], where: str) -> None:
    extra = set(raw) - allowed
    if extra:
        raise ValueError(f"{where}: unexpected fields {sorted(extra)}")


def _id_list(raw: object, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise ValueError(f"{where}: expected an array of card ids")
    return tuple(raw)


def _query(raw: object, where: str, seen: set[str]) -> Query:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: expected an object")
    _reject_unknown_fields(raw, {"id", "kind", "text", "subject", "expect", "forbid"}, where)
    query_id = raw.get("id")
    if not isinstance(query_id, str) or not query_id.strip():
        raise ValueError(f"{where}.id: expected a non-empty string")
    query_id = query_id.strip()
    if query_id in seen:
        raise ValueError(f"{where}: duplicate query id {query_id!r}")
    seen.add(query_id)

    kind = raw.get("kind")
    if kind not in _KINDS:
        raise ValueError(f"{where}.kind: expected one of {sorted(_KINDS)}, got {kind!r}")
    text = raw.get("text")
    if not isinstance(text, str):
        raise ValueError(f"{where}.text: expected a string")
    text = text.strip()
    if not 2 <= len(text) <= 200:
        raise ValueError(f"{where}.text: must be 2-200 characters (API contract)")

    subject = raw.get("subject")
    if subject is not None and subject not in _SUBJECTS:
        raise ValueError(f"{where}.subject: expected math, physics or null")
    expect = _id_list(raw.get("expect"), f"{where}.expect")
    forbid = _id_list(raw.get("forbid"), f"{where}.forbid")

    if kind == "relevant":
        if not expect:
            raise ValueError(f"{where}: relevant queries need a non-empty expect list")
        if forbid:
            raise ValueError(f"{where}: relevant queries do not take forbid")
    elif kind == "filter":
        if subject is None:
            raise ValueError(f"{where}: filter queries need a subject")
        if not expect and not forbid:
            raise ValueError(f"{where}: filter queries need expect or forbid")
    else:
        if expect or forbid or subject is not None:
            raise ValueError(f"{where}: irrelevant queries take no expect/forbid/subject")
    return Query(
        id=query_id,
        kind=kind,
        text=text,
        subject=subject,
        expect=expect,
        forbid=forbid,
    )


def load_queries(path: Path) -> tuple[Query, ...]:
    queries: list[Query] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path.name}:{line_number}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{where}: invalid JSON: {exc.msg}") from exc
        queries.append(_query(raw, where, seen))
    if not queries:
        raise ValueError(f"{path}: no queries")
    return tuple(queries)


def check_against_corpus(queries: tuple[Query, ...], cards: tuple) -> list[str]:
    """Return hard errors; warnings are collected separately by the caller."""

    known = {card.id: card for card in cards}
    errors: list[str] = []
    for query in queries:
        for card_id in query.expect + query.forbid:
            if card_id not in known:
                errors.append(f"{query.id}: unknown card id {card_id!r}")
        if query.kind == "filter" and query.subject is not None:
            for card_id in query.expect:
                if card_id in known and known[card_id].subject != query.subject:
                    errors.append(
                        f"{query.id}: expected {card_id} is {known[card_id].subject}, "
                        f"not the filtered subject {query.subject}"
                    )
        if query.kind == "relevant" and query.subject is not None:
            for card_id in query.expect:
                if card_id in known and known[card_id].subject != query.subject:
                    errors.append(
                        f"{query.id}: expected {card_id} does not match subject {query.subject}"
                    )
    return errors


def uncovered_cards(queries: tuple[Query, ...], cards: tuple) -> list[str]:
    targeted = {card_id for query in queries for card_id in query.expect}
    return sorted(card.id for card in cards if card.id not in targeted)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _corpus_file(settings: KnowledgeSettings) -> Path:
    if settings.corpus_path is not None:
        return settings.corpus_path
    return Path(knowledge_package.__file__).resolve().parent / DEFAULT_CORPUS


def _kept(hits: tuple, threshold: float) -> tuple:
    return tuple(hit for hit in hits if hit.score >= threshold)[:TOP_K]


def _rank(hits: tuple, expect: tuple[str, ...]) -> int | None:
    for index, hit in enumerate(hits, start=1):
        if hit.card.id in expect:
            return index
    return None


def _outcome(query: Query, hits: tuple, threshold: float) -> Outcome:
    kept = _kept(hits, threshold)
    kept_ids = {hit.card.id for hit in kept}
    if query.kind == "relevant":
        top1_ok = bool(kept) and kept[0].card.id in query.expect
        top3_ok = any(card_id in query.expect for card_id in kept_ids)
        ok = top3_ok
    elif query.kind == "filter":
        top1_ok = bool(kept) and kept[0].card.id in query.expect
        top3_ok = any(card_id in query.expect for card_id in kept_ids)
        ok = not any(card_id in query.forbid for card_id in kept_ids) and (
            not query.expect or top3_ok
        )
    else:
        top1_ok = False
        top3_ok = False
        ok = not kept
    return Outcome(
        query=query,
        hits=hits,
        kept=kept,
        rank=_rank(hits, query.expect),
        top1_ok=top1_ok,
        top3_ok=top3_ok,
        ok=ok,
    )


@dataclass(frozen=True, slots=True)
class Summary:
    threshold: float
    total: int
    relevant: int
    filters: int
    irrelevant: int
    covered: int
    top1_ok: int
    top3_ok: int
    filter_ok: int
    rejected: int

    @property
    def top1_rate(self) -> float:
        return self.top1_ok / self.relevant if self.relevant else 0.0

    @property
    def top3_rate(self) -> float:
        return self.top3_ok / self.relevant if self.relevant else 0.0

    @property
    def coverage(self) -> float:
        return self.covered / self.relevant if self.relevant else 0.0

    @property
    def filter_rate(self) -> float:
        return self.filter_ok / self.filters if self.filters else 1.0

    @property
    def reject_rate(self) -> float:
        return self.rejected / self.irrelevant if self.irrelevant else 1.0

    @property
    def passed(self) -> bool:
        return (
            self.top1_rate >= TOP1_GATE
            and self.top3_ok == self.relevant
            and self.filter_ok == self.filters
            and self.rejected == self.irrelevant
        )


def _summarize(scored: tuple[Scored, ...], threshold: float) -> Summary:
    outcomes = tuple(_outcome(item.query, item.hits, threshold) for item in scored)
    relevant = [row for row in outcomes if row.query.kind == "relevant"]
    filters = [row for row in outcomes if row.query.kind == "filter"]
    irrelevant = [row for row in outcomes if row.query.kind == "irrelevant"]
    return Summary(
        threshold=threshold,
        total=len(outcomes),
        relevant=len(relevant),
        filters=len(filters),
        irrelevant=len(irrelevant),
        covered=sum(1 for row in relevant if row.kept),
        top1_ok=sum(1 for row in relevant if row.top1_ok),
        top3_ok=sum(1 for row in relevant if row.top3_ok),
        filter_ok=sum(1 for row in filters if row.ok),
        rejected=sum(1 for row in irrelevant if row.ok),
    )


def _fmt_score(hits: tuple) -> str:
    return f"{hits[0].score:.3f}" if hits else "-"


def _fmt_hit(hit: object) -> str:
    return f"{hit.card.id} {hit.score:.3f}"  # type: ignore[attr-defined]


def _recommended_threshold(scored: tuple[Scored, ...]) -> float | None:
    for threshold in SWEEP:
        if _summarize(scored, threshold).passed:
            return threshold
    return None


def _render(
    *,
    settings: KnowledgeSettings,
    model_name: str,
    dimension: int,
    cards: tuple,
    queries: tuple[Query, ...],
    scored: tuple[Scored, ...],
    default_threshold: float,
    corpus_hash: str,
    query_hash: str,
) -> str:
    summary = _summarize(scored, default_threshold)
    outcomes = tuple(_outcome(item.query, item.hits, default_threshold) for item in scored)
    uncovered = uncovered_cards(queries, cards)
    irrelevant_scores = [
        (row.query.id, row.query.text, row.hits[0].score if row.hits else 0.0)
        for row in outcomes
        if row.query.kind == "irrelevant"
    ]
    irrelevant_scores.sort(key=lambda item: item[2], reverse=True)
    relevant_top_scores = [
        row.hits[0].score for row in outcomes if row.query.kind == "relevant" and row.hits
    ]
    max_irrelevant = max((score for _, _, score in irrelevant_scores), default=0.0)
    min_relevant_top = min(relevant_top_scores, default=0.0)
    passing = [
        threshold
        for threshold in sorted({*SWEEP, default_threshold})
        if _summarize(scored, threshold).passed
    ]
    recommended = _recommended_threshold(scored)
    generated = datetime.now().astimezone().isoformat(timespec="seconds")

    lines = [
        "# 知识卡检索评测报告（RAG v0.1）",
        "",
        f"- 生成时间：{generated}",
        f"- 嵌入模型：`{model_name}`（{dimension} 维；FastEmbed ONNX，CPU 本地推理）",
        f"- 语料：{len(cards)} 张（"
        + " / ".join(
            f"{subject} {sum(1 for card in cards if card.subject == subject)}"
            for subject in ("math", "physics")
        )
        + f"）；sha256 `{corpus_hash[:16]}`",
        f"- 查询集：{len(queries)} 条（relevant "
        f"{sum(1 for query in queries if query.kind == 'relevant')} / filter "
        f"{sum(1 for query in queries if query.kind == 'filter')} / irrelevant "
        f"{sum(1 for query in queries if query.kind == 'irrelevant')}）；"
        f"sha256 `{query_hash[:16]}`",
        f"- 默认阈值：`{default_threshold:.2f}`（`SYNAPSE_RAG_MIN_SCORE`）；"
        f"每次最多返回 {TOP_K} 条",
        f"- 门禁：top-3 = 100%、subject 过滤 = 100%、无关查询拒答 = 100%、top-1 ≥ {TOP1_GATE:.0%}",
        f"- **判定：{'PASS' if summary.passed else 'FAIL'}**",
    ]
    if uncovered:
        lines.append(
            f"- 未被任何查询覆盖的卡：{len(uncovered)} 张（"
            + "、".join(uncovered)
            + "）；仅提示，不计入门禁"
        )

    lines += [
        "",
        "## 汇总（默认阈值）",
        "",
        "| 指标 | 结果 | 门槛 |",
        "|---|---|---|",
        f"| top-1 命中 | {summary.top1_ok}/{summary.relevant} "
        f"（{summary.top1_rate:.1%}） | ≥ {TOP1_GATE:.0%} |",
        f"| top-3 命中 | {summary.top3_ok}/{summary.relevant} （{summary.top3_rate:.1%}） | 100% |",
        f"| 阈值内至少 1 条（覆盖率） | {summary.covered}/{summary.relevant} "
        f"（{summary.coverage:.1%}） | 不单独设门槛 |",
        f"| subject 过滤 | {summary.filter_ok}/{summary.filters} | 100% |",
        f"| 无关查询拒答 | {summary.rejected}/{summary.irrelevant} | 100% |",
        "",
        "无关查询在默认阈值下的最高分（越低越安全）：",
        "",
        "| id | 查询 | 最高分 |",
        "|---|---|---|",
    ]
    for query_id, text, score in irrelevant_scores:
        lines.append(f"| {query_id} | {text} | {score:.3f} |")

    lines += [
        "",
        "## 阈值扫描",
        "",
        f"`覆盖率` = 相关查询在阈值上至少 1 条的比例；`top-1` / `top-3` 分母是全部 "
        f"{summary.relevant} 条相关查询（阈值过高导致无命中按未命中计）。",
        "",
        "| 阈值 | 覆盖率 | top-1 | top-3 | 过滤 | 拒答 | 门禁 |",
        "|---|---|---|---|---|---|---|",
    ]
    sweep_thresholds = sorted({*SWEEP, default_threshold})
    for threshold in sweep_thresholds:
        row = _summarize(scored, threshold)
        marker = " ←默认" if abs(threshold - default_threshold) < 1e-9 else ""
        lines.append(
            f"| {threshold:.2f}{marker} | {row.coverage:.1%} | "
            f"{row.top1_ok}/{row.relevant} | {row.top3_ok}/{row.relevant} | "
            f"{row.filter_ok}/{row.filters} | {row.rejected}/{row.irrelevant} | "
            f"{'PASS' if row.passed else 'FAIL'} |"
        )
    lines += [
        "",
        f"- 扫描范围内最早通过门禁的阈值："
        f"{'`' + format(recommended, '.2f') + '`' if recommended is not None else '无'}",
        "- 通过门禁的扫描阈值："
        + ("、".join(f"`{threshold:.2f}`" for threshold in passing) if passing else "无"),
        f"- 默认阈值比最弱相关查询最高分（{min_relevant_top:.3f}）低 "
        f"{min_relevant_top - default_threshold:.3f}；比最强无关查询（{max_irrelevant:.3f}）高 "
        f"{default_threshold - max_irrelevant:.3f}。",
        "- 阈值只影响展示门槛，不改变排序；提高阈值会让更多相关查询变成空结果。",
    ]

    lines += [
        "",
        "## 逐条结果",
        "",
        "| id | 查询 | 学科过滤 | 期望 | top-1 | 分数 | 期望排名 | 判定 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in outcomes:
        query = row.query
        subject = query.subject or "—"
        if query.kind == "relevant":
            expected = "、".join(query.expect)
            top1 = row.kept[0].card.id if row.kept else "—"
            score = _fmt_score(row.kept)
            verdict = "PASS" if row.top1_ok else ("top3" if row.top3_ok else "MISS")
        elif query.kind == "filter":
            expected = "、".join(query.expect) or "-"
            if query.forbid:
                expected += f"（排除 {'、'.join(query.forbid)}）"
            top1 = row.kept[0].card.id if row.kept else "—"
            score = _fmt_score(row.kept)
            verdict = "PASS" if row.ok else "FAIL"
        else:
            expected = "拒答"
            top1 = row.hits[0].card.id if row.hits else "—"
            score = f"{row.hits[0].score:.3f}" if row.hits else "—"
            verdict = "拒答" if row.ok else "泄漏"
        rank = str(row.rank) if row.rank is not None else "—"
        lines.append(
            f"| {query.id} | {query.text} | {subject} | {expected} | {top1} | "
            f"{score} | {rank} | {verdict} |"
        )

    lines += ["", "## 失败与临界样本", ""]
    failures = [
        row for row in outcomes if not row.ok or (row.query.kind == "relevant" and not row.top1_ok)
    ]
    if not failures:
        lines.append("无：全部门禁项通过。")
    else:
        for row in failures[:MAX_SAMPLE]:
            query = row.query
            detail = "、".join(_fmt_hit(hit) for hit in row.hits[:TOP_K]) or "（无命中）"
            lines.append(f"- `{query.id}` {query.text}")
            lines.append(f"  - 期望：{'、'.join(query.expect) or '拒答'}")
            lines.append(f"  - 实际前 3：{detail}")

    lines += [
        "",
        "## 复现",
        "",
        "```powershell",
        "cd apps/api",
        'pip install -e ".[rag]"',
        "cd ../..",
        "python scripts/eval/knowledge_retrieval.py",
        "# 可选：换阈值 / 换模型 / 换查询集",
        "python scripts/eval/knowledge_retrieval.py --min-score 0.40",
        "python scripts/eval/knowledge_retrieval.py --check",
        "```",
        "",
        f"- 模型缓存：`{settings.cache_dir}`（约 90 MB，不入库；首次运行才下载）",
        "- 无模型时只能跑 `--check`：它校验语料与查询集，不计算语义分数。",
        "- 报告里的 sha256 前 16 位对应语料与查询集的字节内容；换模型或改语料后必须重跑，"
        "不要把不同输入的分数放在一起比较。",
        "",
        "## 边界",
        "",
        "- 查询集由作者按学科概念标签构造，不是教师标注的真实学生提问；56 张卡也不构成学科覆盖。",
        "- top-1/top-3 只说明卡片排序，不说明卡片解释本身正确，也不说明学生看懂了。",
        "- 无关查询只覆盖 6 条，足以做门禁，不足以估计真实拒答率。",
        "- 评测不接触学生原文：查询只有概念标签；检索仍是只读旁路，不改会话与诊断。",
        "- 同一批向量上扫阈值；换嵌入模型后阈值需要重新标定。",
        "",
    ]
    return "\n".join(lines)


def _check(path: Path, corpus: Path | None) -> int:
    cards = load_corpus(corpus)
    queries = load_queries(path)
    errors = check_against_corpus(queries, cards)
    uncovered = uncovered_cards(queries, cards)
    if errors:
        print(f"FAIL: {len(errors)} error(s)")
        for item in errors:
            print(f"  - {item}")
        return 1
    print("OK")
    print(f"  corpus: {len(cards)} cards")
    print(f"  queries: {len(queries)}")
    if uncovered:
        print(f"  warn: {len(uncovered)} card(s) never targeted: {', '.join(uncovered)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--corpus", default=None, help="override the checked-in corpus")
    parser.add_argument("--model", default=None, help="override SYNAPSE_EMBED_MODEL")
    parser.add_argument("--cache-dir", default=None, help="override SYNAPSE_EMBED_CACHE")
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help=f"threshold under test (default: SYNAPSE_RAG_MIN_SCORE or {DEFAULT_MIN_SCORE})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the corpus and query set without loading the model",
    )
    args = parser.parse_args()

    settings = KnowledgeSettings.from_env()
    if args.min_score is not None:
        if not 0.0 <= args.min_score <= 1.0:
            print("! --min-score must be between 0 and 1", file=sys.stderr)
            return 2
        settings = KnowledgeSettings(
            model_name=settings.model_name,
            cache_dir=settings.cache_dir,
            corpus_path=settings.corpus_path,
            min_score=args.min_score,
        )
    if args.corpus:
        settings = KnowledgeSettings(
            model_name=settings.model_name,
            cache_dir=settings.cache_dir,
            corpus_path=Path(args.corpus),
            min_score=settings.min_score,
        )
    if args.model:
        settings = KnowledgeSettings(
            model_name=args.model,
            cache_dir=settings.cache_dir,
            corpus_path=settings.corpus_path,
            min_score=settings.min_score,
        )
    if args.cache_dir:
        settings = KnowledgeSettings(
            model_name=settings.model_name,
            cache_dir=args.cache_dir,
            corpus_path=settings.corpus_path,
            min_score=settings.min_score,
        )

    queries_path = Path(args.queries)
    if args.check:
        return _check(queries_path, settings.corpus_path)

    try:
        cards = load_corpus(settings.corpus_path)
        queries = load_queries(queries_path)
        errors = check_against_corpus(queries, cards)
        if errors:
            for item in errors:
                print(f"! {item}", file=sys.stderr)
            return 2
        embedder = FastEmbedEmbedder(settings.model_name, cache_dir=settings.cache_dir)
        index = InMemoryKnowledgeIndex(cards, embedder, min_score=0.0)
        scored = tuple(
            Scored(
                query=query,
                hits=index.search(query.text, subject=query.subject, limit=5),
            )
            for query in queries
        )
    except (KnowledgeUnavailable, ValueError) as exc:
        print(f"! 评测无法运行：{exc}", file=sys.stderr)
        return 2

    report = _render(
        settings=settings,
        model_name=embedder.model_name,
        dimension=embedder.dimension,
        cards=cards,
        queries=queries,
        scored=scored,
        default_threshold=settings.min_score,
        corpus_hash=_sha256(_corpus_file(settings)),
        query_hash=_sha256(queries_path),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"report: {out}")
    summary = _summarize(scored, settings.min_score)
    return 0 if summary.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
