"""Remove the orphaned ``ir_cron_bridge_switch_check`` cron.

F-09: a previous module version left an ``ir.cron`` record in the database
whose method was renamed (``cron_bridge_switch_check`` ->
``action_switch_all_to_own``). The record is no longer defined in
``data/channel_backend_cron.xml``, but because that file uses ``noupdate="1"``
Odoo never removes it on upgrade, so it keeps failing every 30 minutes with
``AttributeError``.

This migration deletes the orphan by its xmlid only (never by a hardcoded
numeric id, which differs between databases) and is idempotent: if the xmlid
is already gone it exits silently.

``ir.cron`` inherits from ``ir.actions.server`` via ``_inherits``, so the
link lives on the ``ir_cron.ir_actions_server_id`` column, not in
``ir_model_data``. We resolve that id and delete the server action first;
the cron row goes away by cascade.
"""

import logging

_logger = logging.getLogger(__name__)

_MODULE = 'fayna_channel_bridge'
_XMLID = 'ir_cron_bridge_switch_check'


def migrate(cr, version):
    """Delete the orphaned cron and its related records by xmlid."""
    # 1. Locate the ir_model_data row for the orphaned xmlid.
    cr.execute(
        """
        SELECT id, res_id, model
        FROM ir_model_data
        WHERE module = %s AND name = %s
        """,
        (_MODULE, _XMLID),
    )
    row = cr.fetchone()
    if not row:
        _logger.info(
            'Channel Bridge: xmlid %s.%s not found, nothing to clean up',
            _MODULE,
            _XMLID,
        )
        return

    data_id, res_id, model = row

    # 2. Only proceed if the xmlid actually points at an ir.cron record.
    if model != 'ir.cron':
        _logger.info(
            'Channel Bridge: xmlid %s.%s points at model %r, not ir.cron — nothing to clean up',
            _MODULE,
            _XMLID,
            model,
        )
        return

    # 3. Resolve the linked ir.actions.server id (ir.cron _inherits it).
    cr.execute(
        """
        SELECT ir_actions_server_id
        FROM ir_cron
        WHERE id = %s
        """,
        (res_id,),
    )
    cron_row = cr.fetchone()
    if not cron_row:
        _logger.info(
            'Channel Bridge: ir.cron %s for xmlid %s.%s already gone — '
            'cleaning up the stale ir_model_data row only',
            res_id,
            _MODULE,
            _XMLID,
        )
        cr.execute(
            """
            DELETE FROM ir_model_data
            WHERE id = %s
            """,
            (data_id,),
        )
        return

    server_action_id = cron_row[0]

    # 4. Delete the linked ir.actions.server (the cron row cascades away).
    if server_action_id:
        cr.execute(
            """
            DELETE FROM ir_act_server
            WHERE id = %s
            """,
            (server_action_id,),
        )
        act_deleted = cr.rowcount
    else:
        act_deleted = 0

    # 5. Remove the ir.cron row (defensive: it may already be gone by cascade).
    cr.execute(
        """
        DELETE FROM ir_cron
        WHERE id = %s
        """,
        (res_id,),
    )
    cron_deleted = cr.rowcount

    # 6. Remove the ir_model_data row itself.
    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE id = %s
        """,
        (data_id,),
    )

    _logger.info(
        'Channel Bridge: removed orphaned cron xmlid=%s.%s '
        '(ir.cron deleted=%s, ir.act_server deleted=%s)',
        _MODULE,
        _XMLID,
        cron_deleted,
        act_deleted,
    )
