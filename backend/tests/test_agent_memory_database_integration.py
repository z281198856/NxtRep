import os
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.memory import SqlAlchemyMemoryRepository
from nxtrep_backend.services.memory import MemoryService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_memory_direct_write_dedup_version_and_soft_delete() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            owner = User(
                username=f"memory-owner-{uuid4().hex}",
                password_setup_required=False,
            )
            other = User(
                username=f"memory-other-{uuid4().hex}",
                password_setup_required=False,
            )
            session.add_all([owner, other])
            await session.flush()

            service = MemoryService(SqlAlchemyMemoryRepository(session))
            created = await service.create(
                user_id=owner.id,
                category="equipment",
                content="  家里只有一对可调哑铃  ",
            )
            duplicate = await service.create(
                user_id=owner.id,
                category="equipment",
                content="家里只有一对可调哑铃",
            )

            assert duplicate.id == created.id
            assert created.source == "agent_direct"
            assert len(await service.list_memories(user_id=owner.id)) == 1
            assert await service.list_memories(user_id=other.id) == []

            updated = await service.update(
                user_id=owner.id,
                memory_id=created.id,
                expected_version=1,
                category="equipment",
                content="现在有杠铃和深蹲架",
            )
            assert updated.version == 2
            assert updated.content == "现在有杠铃和深蹲架"

            with pytest.raises(RuntimeError, match="Memory was modified"):
                await service.update(
                    user_id=owner.id,
                    memory_id=created.id,
                    expected_version=1,
                    category="equipment",
                    content="错误覆盖",
                )

            deleted = await service.delete(
                user_id=owner.id,
                memory_id=created.id,
                expected_version=2,
            )
            assert deleted.version == 3
            assert deleted.deleted_at is not None
            assert await service.list_memories(user_id=owner.id) == []
        finally:
            await transaction.rollback()
