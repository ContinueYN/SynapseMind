"""Audit the knowledge corpus's citations, offline by default.

The RAG runtime only validates that a source is an https URL with a title and a
license string; it never fetches the page. That is deliberate (retrieval must
stay fast and offline-safe), but it means a stale or mistyped URL can survive in
the corpus unnoticed. This script is the maintenance check:

    python scripts/checks/check_knowledge_sources.py           # metadata only
    python scripts/checks/check_knowledge_sources.py --fetch   # best-effort HTTP

``--fetch`` is opt-in and needs network access. It sends one HEAD request per
unique URL (GET with a one-byte Range as a fallback when HEAD is blocked) and
reports redirects, bot blocks and dead links. Reaching a URL proves nothing
about the card's content, and a 403 can be bot protection rather than a dead
source; the script says which it observed instead of turning either into a
quality claim.

Exit codes: 0 all checks passed, 1 metadata or live checks failed, 2 setup error
(corpus unreadable).
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from synapse.domain.knowledge.models import KnowledgeCard
from synapse.infrastructure.knowledge.corpus import load_corpus

# The corpus test uses the same family: CC licenses and the Python Software
# Foundation license. Keeping the list explicit means adding a source with a new
# license is a reviewed change, not an accidental one.
LICENSE_PREFIXES = ("CC ", "CC0", "PSF-")
USER_AGENT = "SynapseMind-source-audit/0.1 (+local, non-commercial check)"
MAX_WORKERS = 4
_BLOCKED_STATUSES = frozenset({403, 429})


@dataclass(frozen=True, slots=True)
class Issue:
    card_id: str
    url: str
    message: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    status: int | None
    final_url: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 400

    @property
    def blocked(self) -> bool:
        return self.status in _BLOCKED_STATUSES


def audit_metadata(cards: tuple[KnowledgeCard, ...]) -> tuple[Issue, ...]:
    """Check fields the runtime loader does not enforce.

    The loader already requires non-empty text and an https prefix; this pass
    adds the parts a URL can lie about: a host, no embedded credentials, and a
    license in the reviewed family.
    """

    issues: list[Issue] = []
    for card in cards:
        source = card.source
        parsed = urlparse(source.url)
        if parsed.scheme != "https":
            issues.append(Issue(card.id, source.url, "URL is not https"))
        if not parsed.hostname:
            issues.append(Issue(card.id, source.url, "URL has no host"))
        if parsed.username or parsed.password:
            issues.append(Issue(card.id, source.url, "URL embeds credentials"))
        if not source.license.startswith(LICENSE_PREFIXES):
            issues.append(
                Issue(
                    card.id,
                    source.url,
                    f"license {source.license!r} is outside the reviewed "
                    f"prefixes {LICENSE_PREFIXES}",
                )
            )
    return tuple(issues)


def _request(url: str, method: str, timeout: float) -> tuple[int, str, str]:
    headers = {"User-Agent": USER_AGENT}
    if method == "GET":
        headers["Range"] = "bytes=0-0"
    request = Request(url, method=method, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        status = int(response.status)
        final = response.geturl()
        content_type = response.headers.get("content-type", "")
        return status, final, content_type


def fetch_source(url: str, timeout: float) -> FetchResult:
    """Best-effort reachability for one URL; never claims content correctness."""

    try:
        try:
            status, final, content_type = _request(url, "HEAD", timeout)
        except HTTPError as exc:
            if exc.code not in {403, 405, 429}:
                return FetchResult(url, exc.code, str(exc.url), f"HEAD {exc.reason}")
            # Many documentation hosts reject HEAD; a ranged GET is enough to
            # learn whether the page exists without downloading a whole book.
            status, final, content_type = _request(url, "GET", timeout)
    except HTTPError as exc:
        return FetchResult(url, exc.code, str(exc.url), f"HTTP {exc.reason}")
    except URLError as exc:
        return FetchResult(url, None, url, f"network error: {exc.reason}")
    except TimeoutError:
        return FetchResult(url, None, url, f"timeout after {timeout:.1f}s")

    detail = content_type.split(";", 1)[0].strip() or "no content-type"
    return FetchResult(url, status, final, detail)


def _print_metadata(
    cards: tuple[KnowledgeCard, ...], issues: tuple[Issue, ...]
) -> None:
    subjects: dict[str, int] = {}
    licenses: dict[str, int] = {}
    for card in cards:
        subjects[card.subject] = subjects.get(card.subject, 0) + 1
        licenses[card.source.license] = licenses.get(card.source.license, 0) + 1

    print(
        f"corpus: {len(cards)} cards, {len({card.source.url for card in cards})} unique URLs"
    )
    print(
        "subjects: "
        + ", ".join(f"{name} {count}" for name, count in sorted(subjects.items()))
    )
    print(
        "licenses: "
        + ", ".join(f"{name} {count}" for name, count in sorted(licenses.items()))
    )
    if not issues:
        print("metadata: OK")
        return
    print(f"metadata: {len(issues)} issue(s)")
    for issue in issues:
        print(f"  [{issue.card_id}] {issue.message}: {issue.url}")


def _fetch_all(
    cards: tuple[KnowledgeCard, ...], timeout: float
) -> tuple[dict[str, FetchResult], dict[str, list[str]]]:
    owners: dict[str, list[str]] = {}
    for card in cards:
        owners.setdefault(card.source.url, []).append(card.id)

    results: dict[str, FetchResult] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_source, url, timeout): url for url in owners}
        for future in as_completed(futures):
            result = future.result()
            results[result.url] = result
    return results, owners


def _print_fetch(results: dict[str, FetchResult], owners: dict[str, list[str]]) -> int:
    failures = 0
    for url in sorted(owners, key=lambda item: owners[item][0]):
        result = results[url]
        cards = ", ".join(owners[url])
        if result.ok:
            note = (
                f"redirected to {result.final_url}"
                if result.final_url != url
                else result.detail
            )
            print(f"  [ok] {result.status} {cards}: {url} ({note})")
            continue
        failures += 1
        label = "blocked" if result.blocked else "failed"
        print(f"  [{label}] {result.status or '-'} {cards}: {url} ({result.detail})")

    print(f"fetch: {len(results) - failures}/{len(results)} URL(s) reachable")
    if failures:
        print(
            "fetch: not proof that the card content is correct; inspect the URLs above"
        )
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="also send best-effort HTTP requests (requires network access)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="per-request timeout in seconds (default: 10)",
    )
    args = parser.parse_args(argv)

    try:
        cards = load_corpus()
    except (OSError, ValueError) as exc:
        print(f"corpus: {exc}", file=sys.stderr)
        return 2

    issues = audit_metadata(cards)
    _print_metadata(cards, issues)
    if issues:
        return 1

    if not args.fetch:
        print("fetch: skipped (pass --fetch to check reachability; needs network)")
        return 0

    results, owners = _fetch_all(cards, max(0.5, args.timeout))
    return _print_fetch(results, owners)


if __name__ == "__main__":
    raise SystemExit(main())
