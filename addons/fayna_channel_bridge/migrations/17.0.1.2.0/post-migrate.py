"""Backfill ``webhook_path_id`` for existing Telegram backends.

Б-2: the Telegram webhook URL no longer carries the bot token in the path;
instead it uses a random ``webhook_path_id``. Existing ``channel.backend``
records of service ``telegram`` created before this version have an empty
``webhook_path_id``, so their webhook path would be unusable.

This migration generates a value for every such record. It is idempotent:
records that already have a value are left untouched, and re-running the
migration does nothing harmful. Webhook re-registration is deliberately NOT
done here — that is a network call and stays behind the button and the cron.
"""

import logging
import secrets

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Generate ``webhook_path_id`` for Telegram backends that lack one."""
    cr.execute(
        """
        SELECT id
        FROM channel_backend
        WHERE service = %s
          AND (webhook_path_id IS NULL OR webhook_path_id = '')
        """,
        ('telegram',),
    )
    rows = cr.fetchall()
    if not rows:
        _logger.info('Channel Bridge: no Telegram backends to backfill')
        return

    for (rec_id,) in rows:
        cr.execute(
            """
            UPDATE channel_backend
            SET webhook_path_id = %s
            WHERE id = %s
            """,
            (secrets.token_urlsafe(24), rec_id),
        )

    _logger.info(
        'Channel Bridge: backfilled webhook_path_id for %s Telegram backend(s)',
        len(rows),
    )
