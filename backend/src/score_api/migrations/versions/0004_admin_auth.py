"""主办方账号、会话、共享限流及认证审计。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0004_admin_auth"
down_revision = "0003_database_baseline"
branch_labels = None
depends_on = None

OPTIONS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade():
    op.create_table(
        "score_admins",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("login", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("login", name="uq_score_admins_login"),
        **OPTIONS,
    )
    op.create_table(
        "score_admin_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("admin_id", sa.String(32), sa.ForeignKey("score_admins.id"), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("expires_at", DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", DATETIME(fsp=6)),
        **OPTIONS,
    )
    op.create_index("ix_score_admin_sessions_admin_id", "score_admin_sessions", ["admin_id"])
    op.create_index("ix_score_admin_sessions_expires_at", "score_admin_sessions", ["expires_at"])
    op.create_table(
        "score_login_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", DATETIME(fsp=6), nullable=False),
        **OPTIONS,
    )
    op.create_index("ix_score_login_buckets_expires_at", "score_login_buckets", ["expires_at"])
    op.create_table(
        "score_auth_audit",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("admin_id", sa.String(32), sa.ForeignKey("score_admins.id")),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(32), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        **OPTIONS,
    )
    op.create_index("ix_score_auth_audit_admin_id", "score_auth_audit", ["admin_id"])


def downgrade():
    op.drop_table("score_auth_audit")
    op.drop_table("score_login_buckets")
    op.drop_table("score_admin_sessions")
    op.drop_table("score_admins")
