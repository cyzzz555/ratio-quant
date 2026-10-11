"""P1 initial research metadata, with no real account or order tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "001_research"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "underlyings",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("metadata_json", JSONB, nullable=False),
    )
    op.create_table(
        "instruments",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("underlying_id", sa.String, sa.ForeignKey("underlyings.id"), nullable=False),
        sa.Column("metadata_json", JSONB, nullable=False),
    )
    op.create_table(
        "instrument_spec_versions",
        sa.Column("version", sa.String, primary_key=True),
        sa.Column("instrument_id", sa.String, sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", JSONB, nullable=False),
    )
    op.create_table(
        "research_datasets",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("instrument_id", sa.String, sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("data_sha", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest", JSONB, nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", JSONB, nullable=False),
    )
    op.create_index("ix_events_available_at", "events", ["available_at"])
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("code_sha", sa.String, nullable=False),
        sa.Column("parameter_sha", sa.String, nullable=False),
        sa.Column("release_state", sa.String, nullable=False),
    )
    op.create_table(
        "research_runs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("dataset_id", sa.String, sa.ForeignKey("research_datasets.id"), nullable=False),
        sa.Column(
            "strategy_version", sa.String, sa.ForeignKey("strategy_versions.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", JSONB, nullable=False),
    )
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
    )
    op.create_table(
        "risk_locks",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("scope", sa.String, nullable=False),
        sa.Column("reason", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_risk_locks_scope", "risk_locks", ["scope"])
    op.create_table(
        "risk_snapshots",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("scope", sa.String, nullable=False),
        sa.Column("equity", sa.Numeric(38, 18), nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("payload_sha", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in [
        "audit_logs",
        "risk_snapshots",
        "risk_locks",
        "research_jobs",
        "research_runs",
        "strategy_versions",
        "events",
        "research_datasets",
        "instrument_spec_versions",
        "instruments",
        "underlyings",
    ]:
        op.drop_table(table)
