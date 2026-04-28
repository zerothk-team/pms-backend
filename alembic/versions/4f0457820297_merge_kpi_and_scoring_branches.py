"""merge_kpi_and_scoring_branches

Revision ID: 4f0457820297
Revises: 8c420a93904d, d4e5f6a7b8c9
Create Date: 2026-04-27 11:20:11.461578

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f0457820297'
down_revision: Union[str, None] = ('8c420a93904d', 'd4e5f6a7b8c9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
