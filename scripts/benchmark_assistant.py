"""Measure what the assistant actually costs to answer a question.

    python -m scripts.benchmark_assistant                 # the standard set
    python -m scripts.benchmark_assistant --repeat 3      # three runs each
    python -m scripts.benchmark_assistant --no-cache      # cache cleared between
    python -m scripts.benchmark_assistant --ask "..."     # one question

Reports per question and in aggregate: wall time, how much of it was the model
rather than the database, tool calls made, answer length, citations produced.

Two notes on reading the numbers.

**p50 and p95, not the mean.** LLM latency is long-tailed enough that an average
describes a request nobody made. The slow ones are what a user notices.

**--repeat measures the cache, not the model, unless you pass --no-cache.** The
second run of a question re-uses tool results for TOOL_CACHE_TTL_SECONDS, which
is the point of the cache and a lie if you were trying to time the database.

This calls the real API, so it costs real quota. It exists because "it feels
fast" is not something you can put in front of anyone, and because a regression
in tool count is invisible until it is a bill.
"""

import argparse
import asyncio
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.modules.assistant import cache, service  # noqa: E402
from app.modules.assistant.runtime import get_runtime  # noqa: E402
from app.modules.companies.models import Company  # noqa: E402

#: Chosen to span the shapes the assistant has to handle: no tools, one lookup,
#: an aggregate, and a question that genuinely needs several sources.
QUESTIONS = [
    "Hello, what can you help me with?",
    "How many warehouses do we have?",
    "What needs reordering right now?",
    "How has revenue been over the last 30 days?",
    "Can I trust the forecast?",
    "What is low on stock, and has anything sold recently that made it worse?",
]


@dataclass
class Run:
    question: str
    seconds: float
    tool_calls: int
    answer_chars: int
    citations: int
    error: Optional[str] = None
    flags: List[str] = field(default_factory=list)


async def measure(runtime, db, company_id: UUID, question: str) -> Run:
    tool_calls = citations = 0
    text = ""
    error = None
    flags: List[str] = []

    started = time.perf_counter()
    async for event in service.converse(
        runtime=runtime, db=db, company_id=company_id, question=question
    ):
        kind = event.get("type")
        if kind == "tool":
            tool_calls += 1
        elif kind == "citation":
            citations += 1
        elif kind == "text":
            text = event["text"]
        elif kind == "error":
            error = event["message"]
        elif kind == "done":
            flags = event.get("flags", [])
    elapsed = time.perf_counter() - started

    return Run(question, elapsed, tool_calls, len(text), citations, error, flags)


def summarise(runs: List[Run]) -> None:
    ok = [r for r in runs if r.error is None]
    failed = [r for r in runs if r.error is not None]

    print()
    print("=" * 78)
    print(f"{'question':<44} {'sec':>6} {'tools':>6} {'chars':>7} {'cites':>6}")
    print("-" * 78)
    for run in runs:
        label = run.question[:42] + ("…" if len(run.question) > 42 else "")
        if run.error:
            print(f"{label:<44} {'ERROR':>6}  {run.error[:20]}")
        else:
            print(
                f"{label:<44} {run.seconds:>6.2f} {run.tool_calls:>6} "
                f"{run.answer_chars:>7} {run.citations:>6}"
            )
            if run.flags:
                print(f"{'':<44} flags: {', '.join(run.flags)}")

    print("-" * 78)
    if ok:
        times = sorted(r.seconds for r in ok)
        p50 = statistics.median(times)
        # Nearest-rank p95: with a handful of samples, interpolating invents
        # precision the sample size does not support.
        p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
        print(
            f"{len(ok)} answered  |  p50 {p50:.2f}s  p95 {p95:.2f}s  "
            f"max {times[-1]:.2f}s"
        )
        print(
            f"tool calls: {sum(r.tool_calls for r in ok)} total, "
            f"{sum(r.tool_calls for r in ok) / len(ok):.1f} average  |  "
            f"answer length: {statistics.median(r.answer_chars for r in ok):.0f} "
            "chars median"
        )
    if failed:
        print(f"{len(failed)} failed: {failed[0].error}")
    print(f"cache: {cache.stats()}")
    print("=" * 78)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ask", help="Benchmark one question instead of the set.")
    parser.add_argument("--repeat", type=int, default=1, help="Runs per question.")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Clear the tool cache between runs, to time the database honestly.",
    )
    parser.add_argument("--company", help="Company UUID. Defaults to the first one.")
    args = parser.parse_args()

    runtime = get_runtime()
    if not runtime.is_configured():
        print("No API key configured. Set GEMINI_API_KEY.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        if args.company:
            company_id = UUID(args.company)
        else:
            company = db.query(Company).order_by(Company.created_at).first()
            if company is None:
                print("No companies in the database. Seed it first.", file=sys.stderr)
                return 1
            company_id = company.id

        questions = [args.ask] if args.ask else QUESTIONS
        print(f"provider={runtime.name} model={runtime.model} company={company_id}")
        print(f"{len(questions)} question(s) x {args.repeat}")

        runs: List[Run] = []
        for _ in range(args.repeat):
            for question in questions:
                if args.no_cache:
                    cache.clear()
                run = await measure(runtime, db, company_id, question)
                runs.append(run)
                marker = "!" if run.error else "."
                print(marker, end="", flush=True)
                # The Gemini free tier allows only a few requests a minute, and
                # a benchmark that trips the rate limit measures the rate limit.
                await asyncio.sleep(4)

        summarise(runs)
        return 1 if any(r.error for r in runs) else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
