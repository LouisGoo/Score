"""主办方活动草稿、对象、评委及同事务活动审计。

版本：0005_event_drafts
前序：0004_admin_auth
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0005_event_drafts"
down_revision = "0004_admin_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "score_event_audit",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=False),
        sa.Column("before", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("after", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("request_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["score_admins.id"],
            name=op.f("fk_score_event_audit_actor_id_score_admins"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_event_audit")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_score_event_audit_event_created",
        "score_event_audit",
        ["event_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "score_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("organization", sa.String(length=120), nullable=False),
        sa.Column("planned_at", DATETIME(fsp=6), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scoring_rule", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("allow_revisions", sa.Boolean(), nullable=False),
        sa.Column("screen_title", sa.String(length=80), nullable=False),
        sa.Column("screen_theme", sa.String(length=8), nullable=False),
        sa.Column("show_public_qr", sa.Boolean(), nullable=False),
        sa.Column("leaderboard_limit", sa.Integer(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'READY', 'RUNNING', 'FINISHED', 'ARCHIVED')",
            name=op.f("ck_score_events_status"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["score_admins.id"], name=op.f("fk_score_events_owner_id_score_admins")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_events")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_score_events_owner_created",
        "score_events",
        ["owner_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "score_entries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("number", sa.String(length=32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["score_events.id"], name=op.f("fk_score_entries_event_id_score_events")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_entries")),
        sa.UniqueConstraint("event_id", "number", name=op.f("uq_score_entries_event_id")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "score_event_judges",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("number", sa.String(length=32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["score_events.id"],
            name=op.f("fk_score_event_judges_event_id_score_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_event_judges")),
        sa.UniqueConstraint("event_id", "number", name=op.f("uq_score_event_judges_event_id")),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )


def downgrade():
    # 随表删除索引，不能先删除支撑 owner_id 外键的复合索引。
    op.drop_table("score_event_judges")
    op.drop_table("score_entries")
    op.drop_table("score_events")
    op.drop_table("score_event_audit")
