"""results

版本：0011_results
前序：0010_ballots
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0011_results"
down_revision = "0010_ballots"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "score_result_snapshots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("round_id", sa.String(length=32), nullable=False),
        sa.Column("round_version", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(length=32), nullable=False),
        sa.Column("calculation", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("closed_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id", "round_id"],
            ["score_rounds.event_id", "score_rounds.id"],
            name=op.f("fk_score_result_snapshots_event_id_score_rounds"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "rule_id"],
            ["score_event_snapshots.event_id", "score_event_snapshots.id"],
            name=op.f("fk_score_result_snapshots_event_id_score_event_snapshots"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_result_snapshots")),
        sa.UniqueConstraint(
            "round_id", "round_version", name=op.f("uq_score_result_snapshots_round_id")
        ),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.alter_column(
        "score_event_audit", "actor_id", existing_type=mysql.VARCHAR(length=32), nullable=True
    )
    op.add_column("score_rounds", sa.Column("published_at", mysql.DATETIME(fsp=6), nullable=True))


def downgrade():
    op.drop_column("score_rounds", "published_at")
    op.alter_column(
        "score_event_audit", "actor_id", existing_type=mysql.VARCHAR(length=32), nullable=False
    )
    op.drop_table("score_result_snapshots")
