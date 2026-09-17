-- F-03: session, lượt và nhật ký lệnh Clinic.
-- Chưa có chính sách xoá: không tái sử dụng call_id.

CREATE TABLE call_sessions (
    call_id                TEXT PRIMARY KEY,
    start_config           JSONB       NOT NULL,
    opening                JSONB       NOT NULL,
    context                JSONB       NOT NULL,
    context_schema_version INTEGER     NOT NULL,
    last_completed_turn    INTEGER     NOT NULL DEFAULT 0 CHECK (last_completed_turn >= 0),
    ended                  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE call_turns (
    call_id      TEXT        NOT NULL REFERENCES call_sessions (call_id),
    turn         INTEGER     NOT NULL CHECK (turn >= 1),
    input        JSONB       NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL,
    status       TEXT        NOT NULL
        CHECK (status IN ('PROCESSING', 'COMPLETED', 'RECONCILIATION_REQUIRED')),
    result       JSONB,
    extraction   JSONB,
    detail       TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (call_id, turn),
    CHECK (status <> 'COMPLETED' OR result IS NOT NULL)
);

CREATE INDEX call_turns_reconciliation_idx
    ON call_turns (call_id)
    WHERE status = 'RECONCILIATION_REQUIRED';

CREATE TABLE clinic_commands (
    idempotency_key TEXT        PRIMARY KEY,
    call_id         TEXT        NOT NULL,
    turn            INTEGER     NOT NULL,
    operation       TEXT        NOT NULL,
    endpoint        TEXT        NOT NULL,
    payload         JSONB       NOT NULL,
    if_match        INTEGER,
    status          TEXT        NOT NULL CHECK (status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'UNKNOWN')),
    attempts        INTEGER     NOT NULL DEFAULT 1,
    result          JSONB,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (call_id, turn) REFERENCES call_turns (call_id, turn)
);

CREATE INDEX clinic_commands_turn_idx ON clinic_commands (call_id, turn);
