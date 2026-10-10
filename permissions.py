# permissions.py
from discord import app_commands
from discord.ext import commands

from config import OWNER_ID, STAFF_ROLE_IDS


def is_staff_member(ctx: commands.Context) -> bool:
    """
    Shared predicate used both by the global bot check and by the
    per-command decorator below, so the two can never drift apart.

    Staff = the owner, OR anyone with Manage Channels, OR (if configured)
    anyone holding one of STAFF_ROLE_IDS. The role-based path is the
    recommended one for a large server: permissions can be scattered
    across channel overrides, but a role is a single source of truth.
    """
    if is_owner(ctx.author):
        return True

    if ctx.guild is None:
        return False

    channel_permissions = ctx.channel.permissions_for(ctx.author)
    if channel_permissions.manage_channels:
        return True

    if STAFF_ROLE_IDS:
        author_role_ids = {role.id for role in getattr(ctx.author, "roles", [])}
        if author_role_ids.intersection(STAFF_ROLE_IDS):
            return True

    return False


def is_owner(user_or_id) -> bool:
    """Return whether a user or numeric ID is the configured bot owner."""
    return getattr(user_or_id, "id", user_or_id) == OWNER_ID


def member_has_permission(member, permission: str) -> bool:
    """Check one Discord guild permission on a Member or interaction user."""
    return bool(getattr(getattr(member, "guild_permissions", None), permission, False))


def has_permissions_or_owner(**required_permissions):
    """Hybrid-command decorator: owner bypass or all requested guild permissions."""
    async def prefix_check(ctx: commands.Context) -> bool:
        if is_owner(ctx.author):
            return True
        if ctx.guild is None:
            return False
        permissions = ctx.channel.permissions_for(ctx.author)
        return all(getattr(permissions, name, False) for name in required_permissions)

    async def slash_check(interaction) -> bool:
        if is_owner(interaction.user):
            return True
        if interaction.guild is None or interaction.channel is None:
            return False
        permissions = interaction.channel.permissions_for(interaction.user)
        return all(getattr(permissions, name, False) for name in required_permissions)

    def decorator(callback):
        callback = commands.check(prefix_check)(callback)
        callback = app_commands.check(slash_check)(callback)
        return callback

    return decorator


def is_staff_or_owner():
    """Command-level decorator variant of the same check, for cogs that
    want to state their requirement explicitly rather than relying only
    on the global check in main.py."""
    async def predicate(ctx: commands.Context) -> bool:
        return is_staff_member(ctx)
    return commands.check(predicate)
