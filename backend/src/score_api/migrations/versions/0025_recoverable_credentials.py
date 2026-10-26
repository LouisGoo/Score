"""Store encrypted credentials for repeated owner-only viewing.

Revision ID: 0025_recoverable_credentials
Revises: 0018_realtime
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_recoverable_credentials"
down_revision = "0018_realtime"
branch_labels = None
depends_on = None


def upgrade():
    # Existing hashes cannot be reversed; legacy rows stay NULL until set/reset.
    op.add_column(
        "score_event_judges", sa.Column("credential_ciphertext", sa.LargeBinary(), nullable=True)
    )


def downgrade():
    op.drop_column("score_event_judges", "credential_ciphertext")
