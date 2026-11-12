"""Faculty roles and V2 identity/enrollment tables, preserving V1 data."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # upgrade_or_create disables SQLite FK enforcement outside the migration transaction;
    # this prevents batch reconstruction of users from triggering ON DELETE CASCADE.
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_user_role", type_="check")
        batch.create_check_constraint("ck_user_role", "role in ('admin','student','faculty')")
        batch.add_column(sa.Column("email", sa.String(254), nullable=True))
        batch.add_column(sa.Column("account_state", sa.String(24), nullable=False, server_default="ACTIVE"))
        batch.add_column(sa.Column("faculty_id", sa.Integer(), nullable=True))
        batch.create_unique_constraint("uq_user_email", ["email"])
        batch.create_foreign_key("fk_user_faculty", "faculty", ["faculty_id"], ["id"], ondelete="SET NULL")
    for statement in STATEMENTS:
        op.execute(sa.text(statement))


def downgrade():
    raise RuntimeError("Restore the V1 backup and checkout for rollback; automatic downgrade is blocked")


# Frozen DDL: later ORM changes must never change an already-issued migration.
STATEMENTS = (
    "\nCREATE TABLE IF NOT EXISTS v2_mail_outbox (\n\tid INTEGER NOT NULL, \n\tpayload_enc BLOB NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tlast_error VARCHAR(100) NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS v2_semesters (\n\tid INTEGER NOT NULL, \n\tname VARCHAR(80) NOT NULL, \n\tacademic_year VARCHAR(32) NOT NULL, \n\tstart_date DATE NOT NULL, \n\tend_date DATE NOT NULL, \n\trenewal_deadline DATE NOT NULL, \n\treminder_days TEXT NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS v2_section_semesters (\n\tsection_id INTEGER NOT NULL, \n\tsemester_id INTEGER NOT NULL, \n\tPRIMARY KEY (section_id), \n\tFOREIGN KEY(section_id) REFERENCES sections (id) ON DELETE CASCADE, \n\tFOREIGN KEY(semester_id) REFERENCES v2_semesters (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS v2_action_tokens (\n\ttoken_hash VARCHAR(64) NOT NULL, \n\tuser_id INTEGER NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\texpires_at DATETIME NOT NULL, \n\tconsumed_at DATETIME, \n\tPRIMARY KEY (token_hash), \n\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n)\n\n",
    "CREATE INDEX IF NOT EXISTS ix_v2_action_tokens_user_id ON v2_action_tokens (user_id)",
    "\nCREATE TABLE IF NOT EXISTS v2_additional_students (\n\tid INTEGER NOT NULL, \n\tstudent_id INTEGER NOT NULL, \n\tsection_id INTEGER NOT NULL, \n\tcourse_id INTEGER NOT NULL, \n\tstart_date DATE NOT NULL, \n\tend_date DATE, \n\tauthorized_by INTEGER NOT NULL, \n\treason VARCHAR(256) NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(student_id) REFERENCES students (id) ON DELETE CASCADE, \n\tFOREIGN KEY(section_id) REFERENCES sections (id) ON DELETE CASCADE, \n\tFOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE CASCADE, \n\tFOREIGN KEY(authorized_by) REFERENCES users (id)\n)\n\n",
    "\nCREATE TABLE IF NOT EXISTS v2_assignments (\n\tid INTEGER NOT NULL, \n\tfaculty_user_id INTEGER NOT NULL, \n\tsection_id INTEGER NOT NULL, \n\tcourse_id INTEGER, \n\tkind VARCHAR(16) NOT NULL, \n\tstart_date DATE NOT NULL, \n\tend_date DATE, \n\tauthorized_by INTEGER NOT NULL, \n\treason VARCHAR(256) NOT NULL, \n\trevoked BOOLEAN NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(faculty_user_id) REFERENCES users (id) ON DELETE CASCADE, \n\tFOREIGN KEY(section_id) REFERENCES sections (id) ON DELETE CASCADE, \n\tFOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE CASCADE, \n\tFOREIGN KEY(authorized_by) REFERENCES users (id)\n)\n\n",
    "CREATE INDEX IF NOT EXISTS ix_v2_assignments_faculty_user_id ON v2_assignments (faculty_user_id)",
    "\nCREATE TABLE IF NOT EXISTS v2_enrollment_batches (\n\tid VARCHAR(36) NOT NULL, \n\tstudent_id INTEGER NOT NULL, \n\tsemester_id INTEGER NOT NULL, \n\tversion INTEGER NOT NULL, \n\tstatus VARCHAR(32) NOT NULL, \n\tmodel_id VARCHAR(100) NOT NULL, \n\tpipeline_version VARCHAR(128) NOT NULL, \n\tconsent_at DATETIME NOT NULL, \n\tconsent_version VARCHAR(32) NOT NULL, \n\tretain_photos BOOLEAN NOT NULL, \n\tphoto_delete_at DATETIME NOT NULL, \n\texpires_on DATE NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tcc_user_id INTEGER, \n\tcc_verified_at DATETIME, \n\tcc_reason VARCHAR(256) NOT NULL, \n\tadmin_user_id INTEGER, \n\tapproved_at DATETIME, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_v2_enrollment_version UNIQUE (student_id, version), \n\tFOREIGN KEY(student_id) REFERENCES students (id) ON DELETE CASCADE, \n\tFOREIGN KEY(semester_id) REFERENCES v2_semesters (id), \n\tFOREIGN KEY(cc_user_id) REFERENCES users (id) ON DELETE SET NULL, \n\tFOREIGN KEY(admin_user_id) REFERENCES users (id) ON DELETE SET NULL\n)\n\n",
    "CREATE INDEX IF NOT EXISTS ix_v2_enrollment_batches_student_id ON v2_enrollment_batches (student_id)",
    "\nCREATE TABLE IF NOT EXISTS v2_enrollment_samples (\n\tid INTEGER NOT NULL, \n\tbatch_id VARCHAR(36) NOT NULL, \n\tslot INTEGER NOT NULL, \n\tembedding_enc BLOB NOT NULL, \n\tphoto_enc BLOB, \n\tquality TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_v2_sample_slot UNIQUE (batch_id, slot), \n\tFOREIGN KEY(batch_id) REFERENCES v2_enrollment_batches (id) ON DELETE CASCADE\n)\n\n",
    "CREATE INDEX IF NOT EXISTS ix_v2_enrollment_samples_batch_id ON v2_enrollment_samples (batch_id)",
    "\nCREATE TABLE IF NOT EXISTS v2_reminders (\n\tid INTEGER NOT NULL, \n\tbatch_id VARCHAR(36) NOT NULL, \n\tdays_before INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_v2_reminder UNIQUE (batch_id, days_before), \n\tFOREIGN KEY(batch_id) REFERENCES v2_enrollment_batches (id) ON DELETE CASCADE\n)\n\n",
)
