from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import KnowledgeDocument, KnowledgeSource
from nxtrep_backend.repositories.knowledge import SqlAlchemyKnowledgeRepository


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lock", "expects_for_update"),
    [(False, False), (True, True)],
)
async def test_get_document_by_id_can_lock_row(
    lock: bool,
    expects_for_update: bool,
) -> None:
    document_id = uuid4()
    expected_document = MagicMock(spec=KnowledgeDocument)
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=expected_document)
    repository = SqlAlchemyKnowledgeRepository(session)

    result = await repository.get_document_by_id(
        document_id,
        lock=lock,
    )

    assert result is expected_document
    session.scalar.assert_awaited_once()

    statement = session.scalar.await_args.args[0]
    compiled_statement = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert f"knowledge_documents.id = '{document_id}'" in compiled_statement
    assert ("FOR UPDATE" in compiled_statement) is expects_for_update


@pytest.mark.asyncio
async def test_knowledge_repository_flushes_session() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    repository = SqlAlchemyKnowledgeRepository(session)

    await repository.flush()

    session.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_source_by_id_can_lock_row() -> None:
    source_id = uuid4()
    expected_source = MagicMock(spec=KnowledgeSource)
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=expected_source)
    repository = SqlAlchemyKnowledgeRepository(session)

    result = await repository.get_source_by_id(source_id, lock=True)

    assert result is expected_source
    statement = session.scalar.await_args.args[0]
    compiled_statement = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert f"knowledge_sources.id = '{source_id}'" in compiled_statement
    assert "FOR UPDATE" in compiled_statement


@pytest.mark.asyncio
async def test_list_published_documents_filters_source_and_excluded_document() -> None:
    source_id = uuid4()
    excluded_document_id = uuid4()
    expected_document = MagicMock(spec=KnowledgeDocument)
    scalar_result = MagicMock()
    scalar_result.all.return_value = [expected_document]
    session = MagicMock(spec=AsyncSession)
    session.scalars = AsyncMock(return_value=scalar_result)
    repository = SqlAlchemyKnowledgeRepository(session)

    result = await repository.list_published_documents(
        source_id,
        exclude_document_id=excluded_document_id,
        lock=True,
    )

    assert result == [expected_document]
    statement = session.scalars.await_args.args[0]
    compiled_statement = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert f"knowledge_documents.source_id = '{source_id}'" in compiled_statement
    assert (
        f"knowledge_documents.id != '{excluded_document_id}'"
        in compiled_statement
    )
    assert "knowledge_documents.review_status = 'published'" in compiled_statement
    assert "FOR UPDATE" in compiled_statement
