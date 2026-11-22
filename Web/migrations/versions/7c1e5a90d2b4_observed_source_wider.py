import sqlalchemy as sa
from alembic import op


revision = '7c1e5a90d2b4'
down_revision = '4089042564b0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('observed_nodes', schema=None) as batch_op:
        batch_op.alter_column('source', existing_type=sa.String(length=16),
                              type_=sa.String(length=64), existing_nullable=False)


def downgrade():
    with op.batch_alter_table('observed_nodes', schema=None) as batch_op:
        batch_op.alter_column('source', existing_type=sa.String(length=64),
                              type_=sa.String(length=16), existing_nullable=False)
