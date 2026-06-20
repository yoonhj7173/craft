"""flip billing_enabled ON — credit metering / paywall go live (go-live step 13)

The launch flip. With this ON: new users get the signup free-credit grant on first
project, tasks consume grade-weighted credits, the spending cap blocks on depletion
→ auto-paywall. Durable (seed never touches billing_enabled). Reversible via downgrade.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO config (key, value) VALUES ('billing_enabled', 'true') "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    )


def downgrade() -> None:
    # 행 삭제 → _DEFAULTS의 'false'로 폴백(미터링 OFF).
    op.execute("DELETE FROM config WHERE key = 'billing_enabled'")
