"""Load in WeeChat: /soju_read_markers OUTPUT.json [UPGRADE_BASENAME].

With no upgrade name, inspect live buffers. Otherwise use WeeChat's native
upgrade reader (basename in the profile's data directory, without .upgrade).
Unknown markers are reported separately. Never connect, restore sessions, or change markers.
"""

import importlib
import json
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast


class WeeChat(Protocol):
    WEECHAT_RC_OK: int
    WEECHAT_RC_ERROR: int

    def register(
        self,
        name: str,
        author: str,
        version: str,
        license: str,
        description: str,
        shutdown: str,
        charset: str,
    ) -> bool: ...
    def hook_command(
        self,
        name: str,
        description: str,
        args: str,
        args_description: str,
        completion: str,
        callback: str,
        data: str,
    ) -> str: ...
    def prnt(self, buffer: str, message: str) -> None: ...
    def hdata_get(self, name: str) -> str: ...
    def hdata_get_list(self, hdata: str, name: str) -> str: ...
    def hdata_pointer(self, hdata: str, pointer: str, name: str) -> str: ...
    def hdata_integer(self, hdata: str, pointer: str, name: str) -> int: ...
    def hdata_string(self, hdata: str, pointer: str, name: str) -> str: ...
    def hdata_time(self, hdata: str, pointer: str, name: str) -> int: ...
    def buffer_get_string(self, buffer: str, property: str) -> str: ...
    def infolist_next(self, infolist: str) -> int: ...
    def infolist_fields(self, infolist: str) -> str: ...
    def infolist_string(self, infolist: str, name: str) -> str: ...
    def infolist_integer(self, infolist: str, name: str) -> int: ...
    def infolist_time(self, infolist: str, name: str) -> int: ...
    def upgrade_new(self, filename: str, callback: str, data: str) -> str: ...
    def upgrade_read(self, upgrade: str) -> int: ...
    def upgrade_close(self, upgrade: str) -> int: ...


w = cast(WeeChat, importlib.import_module("weechat"))
markers: list[dict[str, str]] = []
unread: list[dict[str, str]] = []
unresolved: list[dict[str, str]] = []
network = target = ""
has_marker = False
all_unread = False


def timestamp(seconds: int, microseconds: int) -> str:
    return (
        datetime.fromtimestamp(seconds, UTC)
        .replace(microsecond=microseconds)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def finish_buffer() -> None:
    if network and target and not has_marker:
        (unread if all_unread else unresolved).append(
            {
                "network": network,
                "target": target,
                **({"scope": "retained_lines"} if all_unread else {"reason": "marker_unavailable"}),
            }
        )


def read_snapshot(data: str, handle: str, object_id: int, infolist: str) -> int:
    global network, target, has_marker, all_unread
    while w.infolist_next(infolist):
        fields = set(w.infolist_fields(infolist).split(","))
        if "s:plugin_name" in fields and "i:first_line_not_read" in fields:
            finish_buffer()
            network = target = ""
            has_marker = False
            all_unread = bool(w.infolist_integer(infolist, "first_line_not_read"))
            if w.infolist_string(infolist, "plugin_name") != "irc":
                continue
            localvars: dict[str, str] = {}
            index = 0
            while f"s:localvar_name_{index:05}" in fields:
                localvars[w.infolist_string(infolist, f"localvar_name_{index:05}")] = (
                    w.infolist_string(infolist, f"localvar_value_{index:05}")
                )
                index += 1
            if localvars.get("type") in ("channel", "private"):
                network = localvars.get("server", "")
                target = localvars.get("channel", "")
        elif "i:last_read_line" in fields and network and target:
            if w.infolist_integer(infolist, "last_read_line"):
                saved_time = timestamp(
                    w.infolist_time(infolist, "date"), w.infolist_integer(infolist, "date_usec")
                )
                markers.append({"network": network, "target": target, "timestamp": saved_time})
                has_marker = True
    return w.WEECHAT_RC_OK


def read_live() -> None:
    hbuffer = w.hdata_get("buffer")
    hlines = w.hdata_get("lines")
    hline = w.hdata_get("line")
    hdata = w.hdata_get("line_data")
    buffer = w.hdata_get_list(hbuffer, "gui_buffers")
    while buffer:
        if (
            w.buffer_get_string(buffer, "localvar_type") in ("channel", "private")
            and w.buffer_get_string(buffer, "plugin") == "irc"
        ):
            server = w.buffer_get_string(buffer, "localvar_server")
            channel = w.buffer_get_string(buffer, "localvar_channel")
            lines = w.hdata_pointer(hbuffer, buffer, "own_lines")
            line = w.hdata_pointer(hlines, lines, "last_read_line") if lines else ""
            if line and server and channel:
                entry = w.hdata_pointer(hline, line, "data")
                markers.append(
                    {
                        "network": server,
                        "target": channel,
                        "timestamp": timestamp(
                            w.hdata_time(hdata, entry, "date"),
                            w.hdata_integer(hdata, entry, "date_usec"),
                        ),
                    }
                )
            elif server and channel:
                is_unread = lines and w.hdata_integer(hlines, lines, "first_line_not_read")
                (unread if is_unread else unresolved).append(
                    {
                        "network": server,
                        "target": channel,
                        **(
                            {"scope": "retained_lines"}
                            if is_unread
                            else {"reason": "marker_unavailable"}
                        ),
                    }
                )
        buffer = w.hdata_pointer(hbuffer, buffer, "next_buffer")


def export_markers(data: str, buffer: str, args: str) -> int:
    global network, target, has_marker, all_unread
    markers.clear()
    unread.clear()
    unresolved.clear()
    network = target = ""
    has_marker = all_unread = False
    try:
        arguments = shlex.split(args)
        if len(arguments) not in (1, 2):
            raise ValueError("Usage: /soju_read_markers OUTPUT.json [UPGRADE_BASENAME]")
        if len(arguments) == 2:
            name = arguments[1]
            if "/" in name or name in (".", ".."):
                raise ValueError("Use an upgrade basename in the data directory, without .upgrade")
            handle = w.upgrade_new(name, "read_snapshot", "")
            if not handle:
                raise ValueError("Cannot open upgrade snapshot")
            try:
                if not w.upgrade_read(handle):
                    raise ValueError("Failed to read upgrade snapshot")
            finally:
                w.upgrade_close(handle)
            finish_buffer()
        else:
            read_live()
        with Path(arguments[0]).expanduser().open("x", encoding="utf-8") as stream:
            json.dump(
                {"version": 1, "markers": markers, "unread": unread, "unresolved": unresolved},
                stream,
                indent=2,
            )
        w.prnt(
            buffer,
            f"Exported {len(markers)} read timestamps, {len(unread)} unread buffers, {len(unresolved)} unknown states.",
        )
    except (ValueError, OSError, OverflowError) as exc:
        w.prnt(buffer, f"Read marker export failed: {exc}")
        return w.WEECHAT_RC_ERROR
    return w.WEECHAT_RC_OK


if w.register(
    "soju_read_markers", "soju-extras", "0.1", "MIT", "Export known read markers", "", ""
):
    w.hook_command(
        "soju_read_markers",
        "Export known read markers without changing state",
        "OUTPUT.json [UPGRADE_BASENAME]",
        "Omit upgrade name for live buffers; existing output files are never overwritten.",
        "",
        "export_markers",
        "",
    )
