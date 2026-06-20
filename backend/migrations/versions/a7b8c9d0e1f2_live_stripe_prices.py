"""swap stripe_prices config to LIVE price ids (go-live step 10)

stripe_prices is a config row (not seeded), so it falls back to the sandbox map in
_DEFAULTS until a DB row overrides it. This upserts the row with the live price ids
created in Stripe live mode. Durable — the seed never touches stripe_prices.

Price ids are not secrets (they reference products, not credentials), safe to commit.
billing_enabled is intentionally NOT flipped here — that is a later, separate step
after live-webhook verification + a real-card smoke charge.

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-06-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIVE_PRICES = (
    '{"starter":"price_1TkLsrRZyUdrj1jeao6DCk7c",'
    '"pro":"price_1TkLssRZyUdrj1jeIQd7ouCr",'
    '"studio":"price_1TkLssRZyUdrj1jeoJdDnsmA",'
    '"pack_s":"price_1TkLstRZyUdrj1jeBOpyYmo5",'
    '"pack_m":"price_1TkLsuRZyUdrj1jeLjjUtDYS",'
    '"pack_l":"price_1TkLsvRZyUdrj1jek1emd6MP"}'
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO config (key, value) VALUES ('stripe_prices', :v) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ).bindparams(v=_LIVE_PRICES)
    )


def downgrade() -> None:
    # 행 삭제 → _DEFAULTS의 sandbox 맵으로 폴백.
    op.execute("DELETE FROM config WHERE key = 'stripe_prices'")
