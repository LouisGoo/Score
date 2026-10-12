"""event_publication

版本：0007_event_publication
前序：0006_judge_credentials
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0007_event_publication"
down_revision = "0006_judge_credentials"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_score_entries_event_pk", "score_entries", ["event_id", "id"])
    op.create_unique_constraint(
        "uq_score_judges_event_pk", "score_event_judges", ["event_id", "id"]
    )
    op.create_table(
        "score_event_snapshots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("scoring_rule", sa.JSON(), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("judges", sa.JSON(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("allow_revisions", sa.Boolean(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["score_events.id"],
            name=op.f("fk_score_event_snapshots_event_id_score_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_event_snapshots")),
        sa.UniqueConstraint("event_id", "id", name="uq_score_snapshots_event_pk"),
        sa.UniqueConstraint("event_id", name=op.f("uq_score_event_snapshots_event_id")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "score_rounds",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("entry_id", sa.String(length=32), nullable=False),
        sa.Column("rule_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'OPEN', 'PAUSED', 'CLOSED', "
            "'PUBLISHED', 'SKIPPED', 'NO_RESULT')",
            name=op.f("ck_score_rounds_status"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "entry_id"],
            ["score_entries.event_id", "score_entries.id"],
            name=op.f("fk_score_rounds_event_id_score_entries"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "rule_id"],
            ["score_event_snapshots.event_id", "score_event_snapshots.id"],
            name=op.f("fk_score_rounds_event_id_score_event_snapshots"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_rounds")),
        sa.UniqueConstraint("event_id", "entry_id", name=op.f("uq_score_rounds_event_id")),
        sa.UniqueConstraint("event_id", "id", name="uq_score_rounds_event_pk"),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "score_round_judges",
        sa.Column("round_id", sa.String(length=32), nullable=False),
        sa.Column("event_judge_id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id", "event_judge_id"],
            ["score_event_judges.event_id", "score_event_judges.id"],
            name=op.f("fk_score_round_judges_event_id_score_event_judges"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "round_id"],
            ["score_rounds.event_id", "score_rounds.id"],
            name=op.f("fk_score_round_judges_event_id_score_rounds"),
        ),
        sa.PrimaryKeyConstraint("round_id", "event_judge_id", name=op.f("pk_score_round_judges")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.add_column(
        "score_events",
        sa.Column("public_code", sa.String(length=12, collation="ascii_bin"), nullable=True),
    )
    op.add_column("score_events", sa.Column("published_at", DATETIME(fsp=6), nullable=True))
    op.add_column(
        "score_events", sa.Column("version", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_unique_constraint(
        op.f("uq_score_events_public_code"), "score_events", ["public_code"]
    )


def downgrade():
    op.drop_table("score_round_judges")
    op.drop_table("score_rounds")
    op.drop_table("score_event_snapshots")
    op.drop_constraint(op.f("uq_score_events_public_code"), "score_events", type_="unique")
    op.drop_column("score_events", "version")
    op.drop_column("score_events", "published_at")
    op.drop_column("score_events", "public_code")
    op.drop_constraint("uq_score_judges_event_pk", "score_event_judges", type_="unique")
    op.drop_constraint("uq_score_entries_event_pk", "score_entries", type_="unique")
