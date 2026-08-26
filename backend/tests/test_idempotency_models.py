from sqlalchemy.dialects.postgresql import JSONB

from nxtrep_backend.db.models import IdempotencyRecord, IdempotencyStatus


def test_idempotency_status_values_are_stable() -> None:
    assert IdempotencyStatus.PROCESSING.value == "processing"
    assert IdempotencyStatus.COMPLETED.value == "completed"


def test_idempotency_record_is_unique_per_user_and_key() -> None:
    constraint_names = {constraint.name for constraint in IdempotencyRecord.__table__.constraints}

    assert "uq_idempotency_records_user_key" in constraint_names


def test_idempotency_record_user_is_deleted_with_account() -> None:
    foreign_key = next(iter(IdempotencyRecord.__table__.c.user_id.foreign_keys))

    assert foreign_key.target_fullname == "users.id"
    assert foreign_key.ondelete == "CASCADE"


def test_idempotency_record_has_state_and_response_constraints() -> None:
    constraint_names = {constraint.name for constraint in IdempotencyRecord.__table__.constraints}

    assert "ck_idempotency_records_operation_not_blank" in constraint_names
    assert "ck_idempotency_records_request_hash_not_blank" in constraint_names
    assert "ck_idempotency_records_status" in constraint_names
    assert "ck_idempotency_records_response_status_range" in constraint_names


def test_idempotency_record_stores_jsonb_response_and_expiration_index() -> None:
    table = IdempotencyRecord.__table__
    indexed_column_sets = {
        tuple(column.name for column in index.columns) for index in table.indexes
    }

    assert isinstance(table.c.response_body.type, JSONB)
    assert ("expires_at",) in indexed_column_sets
    assert ("user_id",) in indexed_column_sets
