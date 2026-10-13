"""snapshots

版本：0013_snapshots
前序：0011_results
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0013_snapshots"
down_revision = "0011_results"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "score_screen_grants",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64, collation="ascii_bin"), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["score_events.id"],
            name=op.f("fk_score_screen_grants_event_id_score_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_screen_grants")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_score_screen_grants_token_hash")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_score_screen_grants_event",
        "score_screen_grants",
        ["event_id", "created_at"],
        unique=False,
    )
    op.add_column(
        "score_event_judges",
        sa.Column("snapshot_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "score_events",
        sa.Column("screen_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "score_events",
        sa.Column("screen_mode", sa.String(length=16), server_default="waiting", nullable=False),
    )
    op.add_column("score_events", sa.Column("screen_round_id", sa.String(length=32), nullable=True))
    # 已发布旧活动从首份快照开始；名单/评分/旧版本不变。
    op.execute("UPDATE score_events SET screen_version = 1 WHERE status <> 'DRAFT'")
    op.execute(
        "UPDATE score_event_judges j JOIN score_events e ON e.id = j.event_id "
        "SET j.snapshot_version = 1 WHERE e.status <> 'DRAFT'"
    )
    op.execute(
        "UPDATE score_events e JOIN score_rounds r ON r.event_id = e.id "
        "SET e.screen_round_id = r.id, "
        "e.screen_mode = CASE WHEN r.status = 'PAUSED' THEN 'paused' ELSE 'progress' END "
        "WHERE r.status IN ('OPEN', 'PAUSED')"
    )
    op.execute(
        "UPDATE score_events SET screen_mode = 'ended' WHERE status IN ('FINISHED', 'ARCHIVED')"
    )


def downgrade():
    op.drop_column("score_events", "screen_round_id")
    op.drop_column("score_events", "screen_mode")
    op.drop_column("score_events", "screen_version")
    op.drop_column("score_event_judges", "snapshot_version")
    # MySQL 以此索引支撑 event_id 外键；随整表一起删除，不能提前单独删除。
    op.drop_table("score_screen_grants")
