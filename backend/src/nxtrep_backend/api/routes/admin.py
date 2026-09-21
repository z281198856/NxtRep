from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from nxtrep_backend.api.deps import AppSettings, CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.knowledge.schemas import KnowledgeLoadRequest, KnowledgeRetrievalRequest
from nxtrep_backend.repositories.knowledge import SqlAlchemyKnowledgeRepository
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository
from nxtrep_backend.schemas.admin import (
    AdminJobResponse,
    AdminUserCreateRequest,
    AdminUserCreateResponse,
    KnowledgeDocumentResponse,
    KnowledgeIngestRequest,
    KnowledgeIngestResponse,
    KnowledgeSearchHitResponse,
    KnowledgeSearchRequest,
    KnowledgeSourceCreateRequest,
    KnowledgeSourceResponse,
)
from nxtrep_backend.services.account import (
    AccountService,
    UsernameAlreadyExistsError,
)
from nxtrep_backend.services.knowledge_document_publication import (
    KnowledgeDocumentPublicationService,
    KnowledgePublicationConflictError,
    KnowledgePublicationNotFoundError,
)
from nxtrep_backend.services.knowledge_document_review import (
    KnowledgeDocumentNotFoundError,
    KnowledgeDocumentReviewConflictError,
    KnowledgeDocumentReviewService,
)
from nxtrep_backend.services.knowledge_ingestion import build_knowledge_ingestion_service
from nxtrep_backend.services.knowledge_retrieval import build_knowledge_retrieval_service
from nxtrep_backend.services.knowledge_source import (
    KnowledgeSourceConflictError,
    KnowledgeSourceService,
)

router = APIRouter()


def _require_admin(user: CurrentUser) -> None:
    if not user.is_admin:
        raise ApiError(
            status_code=403,
            code="ADMIN_REQUIRED",
            message="Administrator permission is required",
        )


@router.post(
    "/users",
    response_model=AdminUserCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    body: AdminUserCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> AdminUserCreateResponse:
    _require_admin(user)

    try:
        created = await AccountService(SqlAlchemyUserRepository(session)).precreate_user(
            username=body.username,
            display_name=body.display_name,
            is_admin=body.is_admin,
        )
    except UsernameAlreadyExistsError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="USERNAME_ALREADY_EXISTS",
            message="Username already exists",
        ) from exc

    profile = created.user.profile
    return AdminUserCreateResponse(
        id=created.user.id,
        username=created.user.username,
        display_name=profile.display_name if profile is not None else None,
        is_admin=created.user.is_admin,
        password_setup_required=created.user.password_setup_required,
        setup_token=created.setup_token,
        setup_token_expires_at=created.setup_token_expires_at,
    )


@router.post(
    "/knowledge/sources",
    response_model=KnowledgeSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_knowledge_source(
    body: KnowledgeSourceCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> KnowledgeSourceResponse:
    _require_admin(user)
    try:
        result = await KnowledgeSourceService(SqlAlchemyKnowledgeRepository(session)).register(
            **body.model_dump()
        )
    except KnowledgeSourceConflictError as exc:
        raise ApiError(status_code=409, code="KNOWLEDGE_SOURCE_CONFLICT", message=str(exc)) from exc
    return KnowledgeSourceResponse.model_validate(result.source, from_attributes=True)


@router.get("/knowledge/sources", response_model=list[KnowledgeSourceResponse])
async def list_knowledge_sources(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[KnowledgeSourceResponse]:
    _require_admin(user)
    items, _ = await SqlAlchemyKnowledgeRepository(session).list_sources(page, page_size)
    return [KnowledgeSourceResponse.model_validate(item, from_attributes=True) for item in items]


@router.post(
    "/knowledge/sources/{source_id}/ingest",
    response_model=KnowledgeIngestResponse,
)
@router.post(
    "/knowledge/sources/{source_id}:ingest",
    response_model=KnowledgeIngestResponse,
    include_in_schema=False,
)
async def ingest_knowledge_source(
    source_id: UUID,
    body: KnowledgeIngestRequest,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
) -> KnowledgeIngestResponse:
    _require_admin(user)
    repository = SqlAlchemyKnowledgeRepository(session)
    source = await repository.get_source_by_id(source_id)
    if source is None:
        raise ApiError(
            status_code=404,
            code="KNOWLEDGE_SOURCE_NOT_FOUND",
            message="Knowledge source not found",
        )
    path = body.path.expanduser().resolve()
    if not path.is_file():
        raise ApiError(
            status_code=422,
            code="KNOWLEDGE_FILE_NOT_FOUND",
            message="Knowledge file not found",
        )
    result = await build_knowledge_ingestion_service(session=session, settings=settings).ingest(
        source_id=source.id,
        request=KnowledgeLoadRequest(
            path=path,
            source_key=source.source_key,
            title=source.title,
            topic=source.topic,
            locale=source.locale,
            content_type=body.content_type,
        ),
    )
    return KnowledgeIngestResponse(**asdict(result))


@router.post(
    "/knowledge/documents/{document_id}/review",
    response_model=KnowledgeDocumentResponse,
)
async def review_knowledge_document(
    document_id: UUID, user: CurrentUser, session: DbSession
) -> KnowledgeDocumentResponse:
    _require_admin(user)
    try:
        result = await KnowledgeDocumentReviewService(
            SqlAlchemyKnowledgeRepository(session)
        ).review(document_id)
    except KnowledgeDocumentNotFoundError as exc:
        raise ApiError(
            status_code=404, code="KNOWLEDGE_DOCUMENT_NOT_FOUND", message=str(exc)
        ) from exc
    except KnowledgeDocumentReviewConflictError as exc:
        raise ApiError(
            status_code=409, code="KNOWLEDGE_DOCUMENT_CONFLICT", message=str(exc)
        ) from exc
    return KnowledgeDocumentResponse.model_validate(result.document, from_attributes=True)


@router.post(
    "/knowledge/documents/{document_id}/publish",
    response_model=KnowledgeDocumentResponse,
)
async def publish_knowledge_document(
    document_id: UUID, user: CurrentUser, session: DbSession
) -> KnowledgeDocumentResponse:
    _require_admin(user)
    try:
        result = await KnowledgeDocumentPublicationService(
            SqlAlchemyKnowledgeRepository(session)
        ).publish(document_id)
    except KnowledgePublicationNotFoundError as exc:
        raise ApiError(
            status_code=404, code="KNOWLEDGE_DOCUMENT_NOT_FOUND", message=str(exc)
        ) from exc
    except KnowledgePublicationConflictError as exc:
        raise ApiError(
            status_code=409, code="KNOWLEDGE_DOCUMENT_CONFLICT", message=str(exc)
        ) from exc
    return KnowledgeDocumentResponse.model_validate(result.document, from_attributes=True)


@router.post("/knowledge/search", response_model=list[KnowledgeSearchHitResponse])
async def search_knowledge(
    body: KnowledgeSearchRequest,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
) -> list[KnowledgeSearchHitResponse]:
    _require_admin(user)
    if body.top_k > body.candidate_k:
        raise ApiError(
            status_code=422,
            code="INVALID_SEARCH_LIMITS",
            message="top_k must not exceed candidate_k",
        )
    hits = await build_knowledge_retrieval_service(session=session, settings=settings).retrieve(
        KnowledgeRetrievalRequest(
            query=body.query,
            topic=body.topic,
            locale=body.locale,
            candidate_k=body.candidate_k,
            top_k=body.top_k,
            source_keys=tuple(body.source_keys),
        )
    )
    return [
        KnowledgeSearchHitResponse(
            **{
                **asdict(hit),
                "page_numbers": list(hit.page_numbers),
                "metadata": dict(hit.metadata),
            }
        )
        for hit in hits
    ]


@router.post("/knowledge/sources/{source_id}/deactivate", response_model=KnowledgeSourceResponse)
@router.post(
    "/knowledge/sources/{source_id}:deactivate",
    response_model=KnowledgeSourceResponse,
    include_in_schema=False,
)
async def deactivate_knowledge_source(
    source_id: UUID, user: CurrentUser, session: DbSession
) -> KnowledgeSourceResponse:
    _require_admin(user)
    repository = SqlAlchemyKnowledgeRepository(session)
    source = await repository.get_source_by_id(source_id, lock=True)
    if source is None:
        raise ApiError(
            status_code=404,
            code="KNOWLEDGE_SOURCE_NOT_FOUND",
            message="Knowledge source not found",
        )
    source.is_active = False
    await repository.flush()
    return KnowledgeSourceResponse.model_validate(source, from_attributes=True)


@router.delete("/knowledge/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_source(
    source_id: UUID, user: CurrentUser, session: DbSession
) -> Response:
    _require_admin(user)
    repository = SqlAlchemyKnowledgeRepository(session)
    source = await repository.get_source_by_id(source_id, lock=True)
    if source is None:
        raise ApiError(
            status_code=404,
            code="KNOWLEDGE_SOURCE_NOT_FOUND",
            message="Knowledge source not found",
        )
    await repository.delete_source(source)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/jobs", response_model=list[AdminJobResponse])
async def list_admin_jobs(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[AdminJobResponse]:
    _require_admin(user)
    sources, _ = await SqlAlchemyKnowledgeRepository(session).list_sources(page, page_size)
    return [
        AdminJobResponse(
            id=item.id,
            status=item.ingest_status,
            source_key=item.source_key,
            error_code=item.last_error_code,
            error_message=item.last_error_message,
            updated_at=item.updated_at,
        )
        for item in sources
    ]


@router.post("/jobs/{job_id}/retry", response_model=KnowledgeIngestResponse)
@router.post(
    "/jobs/{job_id}:retry",
    response_model=KnowledgeIngestResponse,
    include_in_schema=False,
)
async def retry_admin_job(
    job_id: UUID,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
) -> KnowledgeIngestResponse:
    _require_admin(user)
    repository = SqlAlchemyKnowledgeRepository(session)
    source = await repository.get_source_by_id(job_id, lock=True)
    if source is None:
        raise ApiError(
            status_code=404,
            code="ADMIN_JOB_NOT_FOUND",
            message="Background job not found",
        )
    if source.ingest_status not in {"pending", "failed"}:
        raise ApiError(
            status_code=409,
            code="ADMIN_JOB_NOT_RETRYABLE",
            message="Background job is not retryable",
        )
    if source.source_type != "file" or not source.source_uri:
        raise ApiError(
            status_code=409,
            code="ADMIN_JOB_INPUT_UNAVAILABLE",
            message="Source file is unavailable",
        )
    path = Path(source.source_uri).expanduser().resolve()
    if not path.is_file():
        raise ApiError(
            status_code=409,
            code="ADMIN_JOB_INPUT_UNAVAILABLE",
            message="Source file is unavailable",
        )
    content_type = "application/pdf" if path.suffix.casefold() == ".pdf" else "text/html"
    result = await build_knowledge_ingestion_service(session=session, settings=settings).ingest(
        source_id=source.id,
        request=KnowledgeLoadRequest(
            path=path,
            source_key=source.source_key,
            title=source.title,
            topic=source.topic,
            locale=source.locale,
            content_type=content_type,
        ),
    )
    return KnowledgeIngestResponse(**asdict(result))
