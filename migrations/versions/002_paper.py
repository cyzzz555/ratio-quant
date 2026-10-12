"""P3 isolated paper orders, immutable events and transactional outbox."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "002_paper"
down_revision = "001_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_sessions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("state", JSONB, nullable=False),
        sa.Column("cash", sa.Numeric(38, 18), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_events",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, sa.ForeignKey("paper_sessions.id"), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("command_id", sa.String, nullable=False),
        sa.Column("record", JSONB, nullable=False),
        sa.UniqueConstraint("session_id", "sequence"),
        sa.UniqueConstraint("session_id", "command_id"),
    )
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, sa.ForeignKey("paper_sessions.id"), nullable=False),
        sa.Column("client_order_id", sa.String, nullable=False, unique=True),
        sa.Column("plan_hash", sa.String, nullable=False),
        sa.Column("plan", JSONB, nullable=False),
        sa.Column("state", sa.String, nullable=False),
    )
    op.create_table(
        "paper_outbox",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, sa.ForeignKey("paper_sessions.id"), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery", sa.String, nullable=False),
    )


def downgrade() -> None:
    for table in ("paper_outbox", "paper_orders", "paper_events", "paper_sessions"):
        op.drop_table(table)
