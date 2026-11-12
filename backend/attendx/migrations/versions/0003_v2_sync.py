"""Faculty device grants and approved attendance ingestion: frozen DDL."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    for statement in STATEMENTS:
        op.execute(sa.text(statement))


def downgrade():
    raise RuntimeError("Approved attendance must be preserved; restore a verified backup")


STATEMENTS = (
    "\nCREATE TABLE IF NOT EXISTS v2_approved_sessions (\n\tid VARCHAR(36) NOT NULL, \n\tfaculty_user_id INTEGER NOT NULL, \n\tsection_id INTEGER NOT NULL, \n\tcourse_id INTEGER NOT NULL, \n\tdate DATE NOT NULL, \n\tperiod_number INTEGER NOT NULL, \n\trevision INTEGER NOT NULL, \n\tpayload_enc BLOB NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_v2_class_meeting UNIQUE (section_id, course_id, date, period_number), \n\tFOREIGN KEY(faculty_user_id) REFERENCES users (id), \n\tFOREIGN KEY(section_id) REFERENCES sections (id), \n\tFOREIGN KEY(course_id) REFERENCES courses (id)\n)\n\n",
    "CREATE INDEX IF NOT EXISTS ix_v2_approved_sessions_faculty_user_id ON v2_approved_sessions (faculty_user_id)",
    "\nCREATE TABLE IF NOT EXISTS v2_faculty_devices (\n\tid VARCHAR(36) NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tname VARCHAR(80) NOT NULL, \n\tcredential_hash VARCHAR(64) NOT NULL, \n\texpires_at DATETIME NOT NULL, \n\trevoked BOOLEAN NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, \n\tUNIQUE (credential_hash)\n)\n\n",
    "CREATE INDEX IF NOT EXISTS ix_v2_faculty_devices_user_id ON v2_faculty_devices (user_id)",
    "\nCREATE TABLE IF NOT EXISTS v2_attendance_events (\n\tid VARCHAR(36) NOT NULL, \n\tsession_id VARCHAR(36) NOT NULL, \n\tdevice_id VARCHAR(36) NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tpayload_enc BLOB NOT NULL, \n\treceived_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_v2_event_revision UNIQUE (session_id, revision), \n\tFOREIGN KEY(session_id) REFERENCES v2_approved_sessions (id), \n\tFOREIGN KEY(device_id) REFERENCES v2_faculty_devices (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS v2_faculty_grants (\n\tid VARCHAR(36) NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tdevice_id VARCHAR(36), \n\tgenerated_at DATETIME NOT NULL, \n\texpires_at DATETIME NOT NULL, \n\troster_scope TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, \n\tFOREIGN KEY(device_id) REFERENCES v2_faculty_devices (id)\n)\n\n",
)
