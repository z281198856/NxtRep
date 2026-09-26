"""Run the opt-in proactive review as a separately supervised daily worker."""

import argparse
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from nxtrep_backend.cli.run_proactive_review import run
from nxtrep_backend.services.proactive_coach import CHINA_TIMEZONE

logger = logging.getLogger(__name__)
Review = Callable[[date], Awaitable[tuple[int, int, int]]]


@dataclass(slots=True)
class WorkerState:
    completed_dates: set[date] = field(default_factory=set)
    pending_retries: dict[date, datetime] = field(default_factory=dict)
    failure_attempts: dict[date, int] = field(default_factory=dict)


def due_review_date(now: datetime, run_at: time, state: WorkerState) -> date | None:
    local_now = now.astimezone(CHINA_TIMEZONE)
    if (
        local_now.time() >= run_at
        and local_now.date() not in state.completed_dates
        and local_now.date() not in state.pending_retries
    ):
        return local_now.date()
    for review_date, retry_at in sorted(state.pending_retries.items()):
        if local_now >= retry_at:
            return review_date
    return None


def seconds_until_wakeup(now: datetime, run_at: time, state: WorkerState) -> float:
    local_now = now.astimezone(CHINA_TIMEZONE)
    if due_review_date(now, run_at, state) is not None:
        return 0.0
    scheduled_today = datetime.combine(local_now.date(), run_at, tzinfo=CHINA_TIMEZONE)
    next_schedule = (
        scheduled_today if local_now < scheduled_today else scheduled_today + timedelta(days=1)
    )
    wakeups = [next_schedule, *state.pending_retries.values()]
    return max(0.0, (min(wakeups) - local_now).total_seconds())


async def run_due_review(
    review_date: date,
    now: datetime,
    state: WorkerState,
    *,
    review: Review = run,
    retry_after: timedelta = timedelta(minutes=15),
) -> bool:
    """Review once; a partial failure is retried without losing the review date."""
    try:
        users, observations, failed = await review(review_date)
    except Exception as exc:
        logger.error("Proactive worker review failed: %s", type(exc).__name__)
        failed = 1
    else:
        logger.info(
            "Proactive review date=%s users=%s observations=%s failures=%s",
            review_date,
            users,
            observations,
            failed,
        )
    if failed:
        attempts = state.failure_attempts.get(review_date, 0) + 1
        state.failure_attempts[review_date] = attempts
        delay = min(retry_after * (2 ** min(attempts - 1, 5)), timedelta(hours=6))
        state.pending_retries[review_date] = now.astimezone(CHINA_TIMEZONE) + delay
        return False
    state.completed_dates.add(review_date)
    state.pending_retries.pop(review_date, None)
    state.failure_attempts.pop(review_date, None)
    cutoff = now.astimezone(CHINA_TIMEZONE).date() - timedelta(days=14)
    state.completed_dates = {item for item in state.completed_dates if item >= cutoff}
    return True


async def serve_forever(run_at: time, retry_after: timedelta) -> None:
    state = WorkerState()
    while True:
        now = datetime.now(CHINA_TIMEZONE)
        if review_date := due_review_date(now, run_at, state):
            await run_due_review(review_date, now, state, retry_after=retry_after)
            continue
        await asyncio.sleep(max(0.1, seconds_until_wakeup(now, run_at, state)))


def _run_at(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use HH:MM in Asia/Shanghai") from exc
    if len(value) != 5 or value[2] != ":":
        raise argparse.ArgumentTypeError("Use HH:MM in Asia/Shanghai")
    return parsed


def _positive_minutes(value: str) -> int:
    try:
        minutes = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Retry minutes must be a positive integer") from exc
    if minutes < 1:
        raise argparse.ArgumentTypeError("Retry minutes must be a positive integer")
    return minutes


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily opt-in proactive coaching worker")
    parser.add_argument("--at", type=_run_at, default=time(8), metavar="HH:MM")
    parser.add_argument("--retry-minutes", type=_positive_minutes, default=15)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Proactive worker started timezone=Asia/Shanghai at=%s", args.at)
    try:
        asyncio.run(serve_forever(args.at, timedelta(minutes=args.retry_minutes)))
    except KeyboardInterrupt:
        logger.info("Proactive worker stopped")


if __name__ == "__main__":
    main()
