from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import Profile
from nxtrep_backend.repositories.profile import SqlAlchemyProfileRepository


@pytest.mark.asyncio
async def test_get_profile_by_user_id_can_lock_row() -> None:
    user_id = uuid4()
    expected_profile = Profile(
        user_id=user_id,
        version=1,
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=expected_profile)
    repository = SqlAlchemyProfileRepository(session)

    result = await repository.get_by_user_id(
        user_id,
        for_update=True,
    )

    assert result is expected_profile
    statement = session.scalar.await_args.args[0]
    compiled_statement = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert f"profiles.user_id = '{user_id}'" in compiled_statement
    assert "FOR UPDATE" in compiled_statement
