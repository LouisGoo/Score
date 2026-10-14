"""可靠 outbox 投递租约；业务角色版本继续使用既有字段。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0018_realtime"
down_revision = "0013_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("score_outbox", sa.Column("available_at", mysql.DATETIME(fsp=6), nullable=True))
    op.add_column("score_outbox", sa.Column("claim_token", sa.String(32), nullable=True))
    op.create_index(
        "ix_score_outbox_available", "score_outbox", ["delivered_at", "available_at", "id"]
    )


def downgrade():
    op.drop_index("ix_score_outbox_available", table_name="score_outbox")
    op.drop_column("score_outbox", "claim_token")
    op.drop_column("score_outbox", "available_at")
