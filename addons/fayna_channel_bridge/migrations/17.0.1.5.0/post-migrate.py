"""Convert ``channel.provider`` text fields from plain columns to jsonb.

ТЗ §2.6: the catalog text fields were ``translate=False`` and are now
``translate=True``. Odoo stores translatable fields as ``jsonb`` (a dict of
``{lang: value}``). Flipping ``translate`` on an existing model does NOT
automatically wrap the existing plain-text values into jsonb — the ORM alters
the column type, but the old scalar values would be lost or unreadable.

This migration wraps every existing value into the canonical jsonb shape
``{"en_US": <value>}`` so existing ``channel.provider`` rows keep their text
after the update. It is idempotent: rows whose column is already jsonb (or
empty) are left untouched, and re-running does nothing harmful.

Only the fields that became translatable in 17.0.1.5.0 are handled.
"""

import logging

_logger = logging.getLogger(__name__)

# Fields on channel.provider that flipped translate=False -> True in 17.0.1.5.0.
_TRANSLATABLE_FIELDS = [
    "name",
    "token_placeholder",
    "help_url",
    "description",
    "precondition_ids",
    "region_blocklist",
    "cost_warning",
    "side_effect_warning",
    "value_line",
    "permission_line",
    "connect_label",
    "fallback_label",
]


def _column_is_jsonb(cr, table, column):
    """Return True if ``table.column`` is already jsonb (translatable)."""
    cr.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    row = cr.fetchone()
    return bool(row and row[0] == "jsonb")


def migrate(cr, version):
    """Wrap existing plain-text values of translatable fields into jsonb."""
    table = "channel_provider"
    converted = 0
    for field in _TRANSLATABLE_FIELDS:
        if _column_is_jsonb(cr, table, field):
            # Already translatable (jsonb) — nothing to convert.
            continue
        # Wrap non-null, non-empty plain values into {"en_US": value}.
        cr.execute(
            """
            UPDATE channel_provider
            SET {field} = jsonb_build_object('en_US', {field})
            WHERE {field} IS NOT NULL AND {field} != ''
            """.format(field=field)
        )
        converted += cr.rowcount

    if converted:
        _logger.info(
            "Channel Bridge: wrapped %s plain value(s) into jsonb for "
            "translatable channel.provider fields",
            converted,
        )
    else:
        _logger.info("Channel Bridge: no plain channel.provider values to convert")
