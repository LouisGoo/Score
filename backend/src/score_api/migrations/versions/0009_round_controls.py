"""任务时钟、唯一活跃任务约束和到期扫描索引。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0009_round_controls"
down_revision = "0008_judge_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("score_rounds", sa.Column("deadline_at", DATETIME(fsp=6), nullable=True))
    op.add_column("score_rounds", sa.Column("remaining_seconds", sa.Numeric(12, 6), nullable=True))
    op.add_column(
        "score_rounds",
        sa.Column(
            "active_event_id",
            sa.String(32),
            sa.Computed(
                "CASE WHEN status IN ('OPEN', 'PAUSED') THEN event_id ELSE NULL END", persisted=True
            ),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_score_rounds_active_event_id", "score_rounds", ["active_event_id"]
    )
    op.create_check_constraint(
        "remaining", "score_rounds", "remaining_seconds IS NULL OR remaining_seconds >= 0"
    )
    op.create_index("ix_score_rounds_due", "score_rounds", ["status", "deadline_at", "id"])


def downgrade():
    op.drop_index("ix_score_rounds_due", table_name="score_rounds")
    op.drop_constraint(op.f("ck_score_rounds_remaining"), "score_rounds", type_="check")
    op.drop_constraint("uq_score_rounds_active_event_id", "score_rounds", type_="unique")
    op.drop_column("score_rounds", "active_event_id")
    op.drop_column("score_rounds", "remaining_seconds")
    op.drop_column("score_rounds", "deadline_at")
