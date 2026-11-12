"""Persistent encrypted institution-wide classroom authority."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("CREATE TABLE IF NOT EXISTS v2_classroom_authority (id INTEGER NOT NULL PRIMARY KEY, certificate_pem BLOB NOT NULL, private_key_enc BLOB NOT NULL, expires_at DATETIME NOT NULL)"))


def downgrade():
    raise RuntimeError("Preserve the classroom authority and restore a verified backup instead")
