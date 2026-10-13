"""ballots

版本：0010_ballots
前序：0009_round_controls
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0010_ballots"
down_revision = "0009_round_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "score_outbox",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("delivered_at", DATETIME(fsp=6), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["score_events.id"], name=op.f("fk_score_outbox_event_id_score_events")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_outbox")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_score_outbox_pending",
        "score_outbox",
        ["delivered_at", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "score_ballots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("round_id", sa.String(length=32), nullable=False),
        sa.Column("judge_id", sa.String(length=32), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("current_revision >= 1", name=op.f("ck_score_ballots_revision")),
        sa.ForeignKeyConstraint(
            ["event_id", "round_id"],
            ["score_rounds.event_id", "score_rounds.id"],
            name=op.f("fk_score_ballots_event_id_score_rounds"),
        ),
        sa.ForeignKeyConstraint(
            ["round_id", "judge_id"],
            ["score_round_judges.round_id", "score_round_judges.event_judge_id"],
            name=op.f("fk_score_ballots_round_id_score_round_judges"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_ballots")),
        sa.UniqueConstraint("event_id", "id", name="uq_score_ballots_event_pk"),
        sa.UniqueConstraint("round_id", "judge_id", name=op.f("uq_score_ballots_round_id")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "score_ballot_audit",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("ballot_id", sa.String(length=32), nullable=False),
        sa.Column("judge_id", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_revision", sa.Integer(), nullable=True),
        sa.Column("after_revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id", "ballot_id"],
            ["score_ballots.event_id", "score_ballots.id"],
            name=op.f("fk_score_ballot_audit_event_id_score_ballots"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "judge_id"],
            ["score_event_judges.event_id", "score_event_judges.id"],
            name="fk_score_ballot_audit_judge",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_ballot_audit")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_score_ballot_audit_event_created",
        "score_ballot_audit",
        ["event_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "score_ballot_idempotency",
        sa.Column("judge_id", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=36, collation="ascii_bin"), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("ballot_id", sa.String(length=32), nullable=False),
        sa.Column("request_hash", sa.String(length=64, collation="ascii_bin"), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id", "ballot_id"],
            ["score_ballots.event_id", "score_ballots.id"],
            name="fk_score_idempotency_ballot",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "judge_id"],
            ["score_event_judges.event_id", "score_event_judges.id"],
            name=op.f("fk_score_ballot_idempotency_event_id_score_event_judges"),
        ),
        sa.PrimaryKeyConstraint("judge_id", "key", name=op.f("pk_score_ballot_idempotency")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "score_ballot_revisions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("ballot_id", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("computed_total", sa.Numeric(precision=65, scale=30), nullable=False),
        sa.Column("display_total", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("accepted_at", DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_score_ballot_revisions_revision")),
        sa.ForeignKeyConstraint(
            ["event_id", "ballot_id"],
            ["score_ballots.event_id", "score_ballots.id"],
            name=op.f("fk_score_ballot_revisions_event_id_score_ballots"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_ballot_revisions")),
        sa.UniqueConstraint(
            "ballot_id", "revision", name=op.f("uq_score_ballot_revisions_ballot_id")
        ),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )


def downgrade():
    op.drop_table("score_ballot_revisions")
    op.drop_table("score_ballot_idempotency")
    op.drop_index("ix_score_ballot_audit_event_created", table_name="score_ballot_audit")
    op.drop_table("score_ballot_audit")
    op.drop_table("score_ballots")
    op.drop_index("ix_score_outbox_pending", table_name="score_outbox")
    op.drop_table("score_outbox")
