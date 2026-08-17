import shlex

import arrow
import pytimeparse

from server import database
from server.constants import TargetType
from server.exceptions import ClientError, ServerError, ArgumentError
import asyncio

from . import mod_only, list_commands, list_submodules, help

__all__ = [
    "ooc_cmd_motd",
    "ooc_cmd_help",
    "ooc_cmd_kick",
    "ooc_cmd_ban",
    "ooc_cmd_banhdid",
    "ooc_cmd_unban",
    "ooc_cmd_mute",
    "ooc_cmd_unmute",
    "ooc_cmd_login",
    "ooc_cmd_refresh",
    "ooc_cmd_online",
    "ooc_cmd_mods",
    "ooc_cmd_unmod",
    "ooc_cmd_ooc_mute",
    "ooc_cmd_ooc_unmute",
    "ooc_cmd_bans",
    "ooc_cmd_baninfo",
    "ooc_cmd_time",
    "ooc_cmd_whois",
    "ooc_cmd_restart",
    "ooc_cmd_myid",
    "ooc_cmd_multiclients",
]


def ooc_cmd_motd(client, arg):
    """
    Show the message of the day.
    Usage: /motd
    """
    if len(arg) != 0:
        raise ArgumentError("This command doesn't take any arguments")
    client.send_motd()


def ooc_cmd_help(client, arg):
    """
    Show help for a command, or show general help.
    Usage: /help
    """
    import inspect

    if arg == "":
        msg = inspect.cleandoc(
            """
        Welcome to tsuserver3! You can use /help <command> on any known
        command to get up-to-date help on it.
        You may also use /help <category> to see available commands for that category.

        If you don't understand a specific core feature, check the official
        repository for more information:

        https://github.com/Crystalwarrior/KFO-Server/blob/master/README.md 

        Available Categories:
        """
        )
        msg += "\n"
        msg += list_submodules()
        client.send_ooc(msg)
    else:
        arg = arg.lower()
        try:
            if arg in client.server.command_aliases:
                arg = client.server.command_aliases[arg]
            client.send_ooc(help(f"ooc_cmd_{arg}"))
        except AttributeError:
            try:
                msg = f'Submodule "{arg}" commands:\n\n'
                msg += list_commands(arg)
                client.send_ooc(msg)
            except AttributeError:
                client.send_ooc(
                    f"No such command or submodule ({arg}) has been found in the help docs."
                )


@mod_only()
def ooc_cmd_kick(client, arg):
    """
    Kick a player.
    Usage: /kick <ipid|*|**> [reason]
    Special cases:
     - "*" kicks everyone in the current area.
     - "**" kicks everyone in the server.
    """
    if len(arg) == 0:
        raise ArgumentError(
            "You must specify a target. Use /kick <ipid> [reason]")
    elif arg[0] == "*":
        targets = [c for c in client.area.clients if c != client]
    elif arg[0] == "**":
        targets = [c for c in client.server.client_manager.clients if c != client]
    else:
        targets = None

    args = list(arg.split(" "))
    if targets is None:
        raw_ipid = args[0]
        try:
            ipid = int(raw_ipid)
        except Exception:
            raise ClientError(f"{raw_ipid} does not look like a valid IPID.")
        targets = client.server.client_manager.get_targets(
            client, TargetType.IPID, ipid, False
        )

    if targets:
        reason = " ".join(args[1:])
        for c in targets:
            database.log_misc("kick", client, target=c,
                              data={"reason": reason})
            client.send_ooc(f"{c.showname} was kicked.")
            c.send_command("KK", reason)
            c.disconnect()
        client.server.webhooks.kick(c.ipid, reason, client, c.char_name)
    else:
        client.send_ooc(f"No targets with the IPID {ipid} were found.")


def ooc_cmd_ban(client, arg):
    """
    Ban a user. If a ban ID is specified instead of a reason,
    then the IPID is added to an existing ban record.
    Ban durations are 6 hours by default.
    Usage: /ban <ipid> "reason" ["<N> <minute|hour|day|week|month>(s)|perma"]
    Usage 2: /ban <ipid> <ban_id>
    """
    kickban(client, arg, False)


def ooc_cmd_banhdid(client, arg):
    """
    Ban both a user's HDID and IPID.
    Usage: See /ban.
    """
    kickban(client, arg, True)


@mod_only()
def kickban(client, arg, ban_hdid):
    args = shlex.split(arg)
    if len(args) < 2:
        raise ArgumentError("Not enough arguments.")
    elif len(args) == 2:
        reason = None
        ban_id = None
        try:
            ban_id = int(args[1])
            unban_date = None
        except ValueError:
            reason = args[1]
            unban_date = arrow.get().shift(hours=6).datetime
    elif len(args) == 3:
        ban_id = None
        reason = args[1]
        if "perma" in args[2]:
            unban_date = None
        else:
            duration = pytimeparse.parse(args[2], granularity="hours")
            if duration is None:
                raise ArgumentError("Invalid ban duration.")
            unban_date = arrow.get().shift(seconds=duration).datetime
    else:
        raise ArgumentError(
            f"Ambiguous input: {arg}\nPlease wrap your arguments " "in quotes."
        )

    try:
        raw_ipid = args[0]
        ipid = int(raw_ipid)
    except ValueError:
        raise ClientError(f"{raw_ipid} does not look like a valid IPID.")

    ban_id = database.ban(
        ipid,
        reason,
        ban_type="ipid",
        banned_by=client,
        ban_id=ban_id,
        unban_date=unban_date,
    )

    char = None
    hdid = None
    if ipid is not None:
        targets = client.server.client_manager.get_targets(
            client, TargetType.IPID, ipid, False
        )
        if targets:
            for c in targets:
                if ban_hdid:
                    database.ban(c.hdid, reason,
                                 ban_type="hdid", ban_id=ban_id)
                    hdid = c.hdid
                c.send_command("KB", reason)
                c.disconnect()
                char = c.char_name
                database.log_misc("ban", client, target=c,
                                  data={"reason": reason})
            client.send_ooc(f"{len(targets)} clients were kicked.")
        client.send_ooc(f"{ipid} was banned. Ban ID: {ban_id}")
    client.server.webhooks.ban(
        ipid, ban_id, reason, client, hdid, char, unban_date)


@mod_only()
def ooc_cmd_unban(client, arg):
    """
    Unban a list of users.
    Usage: /unban <ban_id...>
    """
    if len(arg) == 0:
        raise ArgumentError(
            "You must specify a target. Use /unban <ban_id...>")
    args = list(arg.split(" "))
    client.send_ooc(f"Attempting to lift {len(args)} ban(s)...")
    for ban_id in args:
        if database.unban(ban_id):
            client.send_ooc(f"Removed ban ID {ban_id}.")
            client.server.webhooks.unban(ban_id, client)
        else:
            client.send_ooc(f"{ban_id} is not on the ban list.")
        database.log_misc("unban", client, data={"id": ban_id})


@mod_only()
def ooc_cmd_mute(client, arg):
    """
    Prevent a user from speaking in-character.
    Usage: /mute <ipid>
    """
    if len(arg) == 0:
        raise ArgumentError("You must specify a target. Use /mute <ipid>.")
    args = list(arg.split(" "))
    client.send_ooc(f"Attempting to mute {len(args)} IPIDs.")
    for raw_ipid in args:
        if raw_ipid.isdigit():
            ipid = int(raw_ipid)
            clients = client.server.client_manager.get_targets(
                client, TargetType.IPID, ipid, False
            )
            if clients:
                msg = "Muted the IPID " + str(ipid) + "'s following clients:"
                for c in clients:
                    c.is_muted = True
                    database.log_misc("mute", client, target=c)
                    msg += " " + c.showname + " [" + str(c.id) + "],"
                msg = msg[:-1]
                msg += "."
                client.send_ooc(msg)
            else:
                client.send_ooc(
                    "No targets found. Use /mute <ipid> <ipid> ... for mute."
                )
        else:
            client.send_ooc(f"{raw_ipid} does not look like a valid IPID.")


@mod_only()
def ooc_cmd_unmute(client, arg):
    """
    Unmute a user.
    Usage: /unmute <ipid>
    """
    if len(arg) == 0:
        raise ArgumentError("You must specify a target.")
    args = list(arg.split(" "))
    client.send_ooc(f"Attempting to unmute {len(args)} IPIDs.")
    for raw_ipid in args:
        if raw_ipid.isdigit():
            ipid = int(raw_ipid)
            clients = client.server.client_manager.get_targets(
                client, TargetType.IPID, ipid, False
            )
            if clients:
                msg = f"Unmuted the IPID ${str(ipid)}'s following clients:"
                for c in clients:
                    c.is_muted = False
                    database.log_misc("unmute", client, target=c)
                    msg += " " + c.showname + " [" + str(c.id) + "],"
                msg = msg[:-1]
                msg += "."
                client.send_ooc(msg)
            else:
                client.send_ooc(
                    "No targets found. Use /unmute <ipid> <ipid> ... for unmute."
                )
        else:
            client.send_ooc(f"{raw_ipid} does not look like a valid IPID.")


def ooc_cmd_login(client, arg):
    """
    Login as a moderator.

