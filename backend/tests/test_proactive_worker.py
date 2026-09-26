from datetime import date, datetime, time, timedelta

import pytest

from nxtrep_backend.cli.run_proactive_worker import (
    WorkerState,
    due_review_date,
    run_due_review,
    seconds_until_wakeup,
)
from nxtrep_backend.services.proactive_coach import CHINA_TIMEZONE


def test_daily_worker_waits_until_local_time_and_rechecks_safely_after_restart():
    run_at = time(8)
    state = WorkerState()
    before = datetime(2026, 9, 26, 7, 59, tzinfo=CHINA_TIMEZONE)
    due = datetime(2026, 9, 26, 8, 1, tzinfo=CHINA_TIMEZONE)
    assert due_review_date(before, run_at, state) is None
    assert seconds_until_wakeup(before, run_at, state) == 60
    assert due_review_date(due, run_at, state) == date(2026, 9, 26)
    state.completed_dates.add(date(2026, 9, 26))
    assert due_review_date(due, run_at, state) is None
    assert seconds_until_wakeup(due, run_at, state) == 23 * 3600 + 59 * 60
    assert due_review_date(due, run_at, WorkerState()) == date(2026, 9, 26)


@pytest.mark.asyncio
async def test_partial_failure_retries_old_day_without_blocking_next_day():
    state = WorkerState()
    first_day = date(2026, 9, 25)
    second_day = date(2026, 9, 26)
    started = datetime(2026, 9, 25, 8, 0, tzinfo=CHINA_TIMEZONE)

    async def partially_failed(_: date) -> tuple[int, int, int]:
        return 3, 2, 1

    assert not await run_due_review(first_day, started, state, review=partially_failed)
    assert state.pending_retries[first_day] == started + timedelta(minutes=15)
    assert due_review_date(started + timedelta(minutes=14), time(8), state) is None
    assert seconds_until_wakeup(started + timedelta(minutes=14), time(8), state) == 60
    assert due_review_date(started + timedelta(minutes=15), time(8), state) == first_day
    assert not await run_due_review(
        first_day, started + timedelta(minutes=15), state, review=partially_failed
    )
    assert state.pending_retries[first_day] == started + timedelta(minutes=45)

    next_morning = datetime(2026, 9, 26, 8, 0, tzinfo=CHINA_TIMEZONE)
    assert due_review_date(next_morning, time(8), state) == second_day

    async def succeeded(_: date) -> tuple[int, int, int]:
        return 3, 2, 0

    assert await run_due_review(second_day, next_morning, state, review=succeeded)
    assert due_review_date(next_morning, time(8), state) == first_day
    assert await run_due_review(first_day, next_morning, state, review=succeeded)
    assert state.pending_retries == {}
    assert state.failure_attempts == {}
    assert state.completed_dates == {first_day, second_day}


@pytest.mark.asyncio
async def test_exception_stays_retryable_without_completing_day():
    state = WorkerState()
    review_date = date(2026, 9, 26)
    now = datetime(2026, 9, 26, 8, 0, tzinfo=CHINA_TIMEZONE)

    async def unavailable(_: date) -> tuple[int, int, int]:
        raise RuntimeError("database temporarily unavailable")

    assert not await run_due_review(review_date, now, state, review=unavailable)
    assert review_date not in state.completed_dates
    assert due_review_date(now + timedelta(minutes=15), time(8), state) == review_date
