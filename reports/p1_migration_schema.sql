BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 001_research

CREATE TABLE underlyings (
    id VARCHAR NOT NULL, 
    metadata_json JSONB NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE instruments (
    id VARCHAR NOT NULL, 
    underlying_id VARCHAR NOT NULL, 
    metadata_json JSONB NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(underlying_id) REFERENCES underlyings (id)
);

CREATE TABLE instrument_spec_versions (
    version VARCHAR NOT NULL, 
    instrument_id VARCHAR NOT NULL, 
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    metadata_json JSONB NOT NULL, 
    PRIMARY KEY (version), 
    FOREIGN KEY(instrument_id) REFERENCES instruments (id)
);

CREATE TABLE research_datasets (
    id VARCHAR NOT NULL, 
    instrument_id VARCHAR NOT NULL, 
    data_sha VARCHAR NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    manifest JSONB NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(instrument_id) REFERENCES instruments (id)
);

CREATE TABLE events (
    id VARCHAR NOT NULL, 
    available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    metadata_json JSONB NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_events_available_at ON events (available_at);

CREATE TABLE strategy_versions (
    id VARCHAR NOT NULL, 
    code_sha VARCHAR NOT NULL, 
    parameter_sha VARCHAR NOT NULL, 
    release_state VARCHAR NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE research_runs (
    id VARCHAR NOT NULL, 
    dataset_id VARCHAR NOT NULL, 
    strategy_version VARCHAR NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    result JSONB NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(dataset_id) REFERENCES research_datasets (id), 
    FOREIGN KEY(strategy_version) REFERENCES strategy_versions (id)
);

CREATE TABLE research_jobs (
    id VARCHAR NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    state VARCHAR NOT NULL, 
    snapshot JSONB NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE risk_locks (
    id VARCHAR NOT NULL, 
    scope VARCHAR NOT NULL, 
    reason VARCHAR NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_risk_locks_scope ON risk_locks (scope);

CREATE TABLE risk_snapshots (
    id VARCHAR NOT NULL, 
    scope VARCHAR NOT NULL, 
    equity NUMERIC(38, 18) NOT NULL, 
    snapshot JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE audit_logs (
    id VARCHAR NOT NULL, 
    action VARCHAR NOT NULL, 
    payload_sha VARCHAR NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

INSERT INTO alembic_version (version_num) VALUES ('001_research') RETURNING alembic_version.version_num;

COMMIT;

