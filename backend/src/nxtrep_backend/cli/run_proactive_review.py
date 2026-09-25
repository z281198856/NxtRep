"""Run opt-in proactive coaching checks once per local day.

Schedule this command externally; duplicate invocations are safe because each
observation uses a deterministic notification ID.
"""

import argparse
import asyncio
import logging
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select

from nxtrep_backend.db.models import NotificationSetting
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.services.proactive_coach import CHINA_TIMEZONE, ProactiveCoachService

logger = logging.getLogger(__name__)


async def run(today: date) -> tuple[int, int, int]:
    reviewed = observations = failed = 0
    last_user_id: UUID | None = None
    while True:
        async with SessionFactory() as session:
            statement = select(NotificationSetting.user_id).where(
                NotificationSetting.enabled.is_(True),
                NotificationSetting.categories["proactive_coach"].as_boolean().is_(True),
            )
            if last_user_id is not None:
                statement = statement.where(NotificationSetting.user_id > last_user_id)
            user_ids = list(
                await session.scalars(statement.order_by(NotificationSetting.user_id).limit(100))
            )
        if not user_ids:
            break
        for user_id in user_ids:
            try:
                async with SessionFactory() as session:
                    notices = await ProactiveCoachService(session).review_user(user_id, today)
                    await session.commit()
                reviewed += 1
                observations += len(notices)
            except Exception as exc:
                # A single account must not prevent reviews for other accounts.
                failed += 1
                logger.error("Proactive review failed for one account: %s", type(exc).__name__)
        last_user_id = user_ids[-1]
    return reviewed, observations, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Run opt-in proactive coaching review")
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    today = args.date or datetime.now(CHINA_TIMEZONE).date()
    reviewed, notices, failed = asyncio.run(run(today))
    print(f"review_date={today} users={reviewed} observations={notices} failures={failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
