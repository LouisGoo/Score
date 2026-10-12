"""评委凭证；仅保存验证哈希和二进制 HMAC。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0006_judge_credentials"
down_revision = "0005_event_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("score_event_judges", sa.Column("credential_hash", sa.String(256)))
    op.add_column("score_event_judges", sa.Column("credential_lookup", sa.BINARY(32)))
    op.add_column("score_event_judges", sa.Column("credential_source", sa.String(16)))
    op.add_column(
        "score_event_judges",
        sa.Column("credential_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("score_event_judges", sa.Column("credential_updated_at", DATETIME(fsp=6)))
    op.create_unique_constraint(
        "uq_score_judges_event_credential", "score_event_judges", ["event_id", "credential_lookup"]
    )
    op.create_check_constraint(
        "credential_complete",
        "score_event_judges",
        "(credential_hash IS NULL AND credential_lookup IS NULL "
        "AND credential_source IS NULL AND credential_updated_at IS NULL "
        "AND credential_version = 0) OR "
        "(credential_hash IS NOT NULL AND credential_lookup IS NOT NULL "
        "AND credential_source IN ('generated', 'manual') "
        "AND credential_source IS NOT NULL AND credential_updated_at IS NOT NULL "
        "AND credential_version > 0)",
    )


def downgrade():
    op.drop_constraint(
        op.f("ck_score_event_judges_credential_complete"), "score_event_judges", type_="check"
    )
    op.drop_constraint("uq_score_judges_event_credential", "score_event_judges", type_="unique")
    for name in (
        "credential_updated_at",
        "credential_version",
        "credential_source",
        "credential_lookup",
        "credential_hash",
    ):
        op.drop_column("score_event_judges", name)
