"""Store the host's restart-safe continuity source revisions on the owning chat."""

from alembic import op
import sqlalchemy as sa

revision = 'd59b632a4c18'
down_revision = '9f6c2a8d1b43'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chat', sa.Column('dissipative_source_state', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('chat', 'dissipative_source_state')
