"""judge_sessions

版本：0008_judge_sessions
前序：0007_event_publication
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0008_judge_sessions"
down_revision = "0007_event_publication"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "score_judge_auth_audit",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("judge_id", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id", "judge_id"],
            ["score_event_judges.event_id", "score_event_judges.id"],
            name=op.f("fk_score_judge_auth_audit_event_id_score_event_judges"),
        ),
        sa.ForeignKeyConstraint(["event_id"], ["score_events.id"], name="fk_judge_audit_event"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_judge_auth_audit")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_score_judge_auth_audit_event_created",
        "score_judge_auth_audit",
        ["event_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "score_judge_confirmations",
        sa.Column("token_hash", sa.String(length=64, collation="ascii_bin"), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("judge_id", sa.String(length=32), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("bootstrap_hash", sa.String(length=64, collation="ascii_bin"), nullable=False),
        sa.Column("expires_at", DATETIME(fsp=6), nullable=False),
        sa.Column("consumed_at", DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id", "judge_id"],
            ["score_event_judges.event_id", "score_event_judges.id"],
            name=op.f("fk_score_judge_confirmations_event_id_score_event_judges"),
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_score_judge_confirmations")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_score_judge_confirmations_expiry",
        "score_judge_confirmations",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "score_judge_sessions",
        sa.Column("token_hash", sa.String(length=64, collation="ascii_bin"), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("judge_id", sa.String(length=32), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("expires_at", DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", DATETIME(fsp=6), nullable=True),
        sa.Column(
            "active_judge_id",
            sa.String(length=32),
            sa.Computed("CASE WHEN revoked_at IS NULL THEN judge_id ELSE NULL END", persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "judge_id"],
            ["score_event_judges.event_id", "score_event_judges.id"],
            name=op.f("fk_score_judge_sessions_event_id_score_event_judges"),
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_score_judge_sessions")),
        sa.UniqueConstraint(
            "active_judge_id", name=op.f("uq_score_judge_sessions_active_judge_id")
        ),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_score_judge_sessions_expiry", "score_judge_sessions", ["expires_at"], unique=False
    )


def downgrade():
    op.drop_table("score_judge_sessions")
    op.drop_table("score_judge_confirmations")
    op.drop_table("score_judge_auth_audit")
