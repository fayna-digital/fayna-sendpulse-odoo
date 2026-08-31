"""Post-init hooks for the Fayna Channel Bridge module.

These hooks run once when the module is installed (and on upgrade) and
guarantee that every Odoo administrator (member of ``base.group_system``)
is automatically granted the Channel Bridge groups.

This is the canonical way to make a module's menus visible to admins
without hardcoding user IDs or requiring manual group assignment.
"""


def _channel_bridge_groups(env):
    """Return the Channel Bridge group records (officer + administrator)."""
    officer = env.ref(
        'fayna_channel_bridge.group_channel_bridge_officer',
        raise_if_not_found=False,
    )
    admin = env.ref(
        'fayna_channel_bridge.group_channel_bridge_admin',
        raise_if_not_found=False,
    )
    groups = env['res.groups']
    if officer:
        groups |= officer
    if admin:
        groups |= admin
    return groups


def post_init_hook(env):
    """Assign the Channel Bridge groups to every system administrator.

    Runs on module install. Idempotent: ``_write`` on the many2many
    ``users`` field only adds memberships that are not already present.
    """
    groups = _channel_bridge_groups(env)
    if not groups:
        return
    admins = env.ref('base.group_system').users
    for group in groups:
        group.write({'users': [(4, admin.id) for admin in admins]})
