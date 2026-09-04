"""Pre-migration script for fayna_channel_bridge 17.0.1.6.0.

This script resolves a model conflict for the xmlid
'fayna_channel_bridge.action_channel_provider' which was previously
defined as ir.actions.act_window but is now defined as ir.actions.client
in the new version. The script removes the existing act_window record
and its xmlid reference to allow the new client action to be created
during data import.

The script is idempotent and safe to run multiple times.
"""

import logging

_logger = logging.getLogger(__name__)

MODULE = 'fayna_channel_bridge'
XMLID = 'action_channel_provider'
OLD_MODEL = 'ir.actions.act_window'
NEW_MODEL = 'ir.actions.client'
MENU_ACTION_TEMPLATE = 'ir.actions.act_window,%s'


def migrate(cr, version):
    """Remove conflicting act_window record for action_channel_provider xmlid."""
    cr.execute(
        """SELECT model, res_id
           FROM ir_model_data
           WHERE module = %s AND name = %s""",
        (MODULE, XMLID),
    )
    row = cr.fetchone()
    if row is None:
        _logger.info('No existing xmlid %s.%s found. Nothing to migrate.', MODULE, XMLID)
        return

    model, res_id = row
    if model == NEW_MODEL:
        _logger.info(
            'Xmlid %s.%s already points to %s. Migration already applied.', MODULE, XMLID, NEW_MODEL
        )
        return
    if model != OLD_MODEL:
        _logger.warning(
            'Unexpected model %s for xmlid %s.%s. Expected %s. Skipping migration.',
            model,
            MODULE,
            XMLID,
            OLD_MODEL,
        )
        return

    _logger.info(
        'Found conflicting xmlid %s.%s pointing to %s (res_id=%s). '
        'Removing to allow new %s definition.',
        MODULE,
        XMLID,
        OLD_MODEL,
        res_id,
        NEW_MODEL,
    )

    # Remove menu reference to avoid broken menu if migration fails midway
    cr.execute(
        """UPDATE ir_ui_menu
           SET action = NULL
           WHERE action = %s""",
        (MENU_ACTION_TEMPLATE % res_id,),
    )
    # Delete the act_window record from both ir_act_window and ir_actions tables.
    # The record exists in two tables without FK cascade, so both must be cleaned.
    cr.execute("""DELETE FROM ir_act_window WHERE id = %s""", (res_id,))
    cr.execute("""DELETE FROM ir_actions WHERE id = %s""", (res_id,))
    # Delete the xmlid record
    cr.execute(
        """DELETE FROM ir_model_data
           WHERE module = %s AND name = %s""",
        (MODULE, XMLID),
    )
    _logger.info(
        'Removed ir_act_window and ir_actions records id=%s and ir_model_data for %s.%s',
        res_id,
        MODULE,
        XMLID,
    )
