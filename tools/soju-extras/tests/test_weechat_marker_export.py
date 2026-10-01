"""Marker extraction must include event lines and explicitly account for unknowns."""

import runpy
import sys
from pathlib import Path

import pytest


class SnapshotAPI:
    WEECHAT_RC_OK = 0
    WEECHAT_RC_ERROR = 1

    def __init__(self) -> None:
        self.record: dict[str, int | str] = {}
        self.pending = False

    def register(self, *args: object) -> bool:
        return False

    def infolist_next(self, pointer: str) -> int:
        result, self.pending = self.pending, False
        return int(result)

    def infolist_fields(self, pointer: str) -> str:
        return ",".join(
            f"{'i' if isinstance(value, int) else 's'}:{name}"
            for name, value in self.record.items()
        )

    def infolist_string(self, pointer: str, name: str) -> str:
        value = self.record[name]
        assert isinstance(value, str)
        return value

    def infolist_integer(self, pointer: str, name: str) -> int:
        value = self.record[name]
        assert isinstance(value, int)
        return value

    def infolist_time(self, pointer: str, name: str) -> int:
        return self.infolist_integer(pointer, name)


def test_snapshot_markers_include_events_and_report_trimmed_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = SnapshotAPI()
    monkeypatch.setitem(sys.modules, "weechat", api)
    script = runpy.run_path(str(Path(__file__).parents[1] / "contrib/weechat_read_markers.py"))

    def read(record: dict[str, int | str]) -> None:
        api.record, api.pending = record, True
        assert script["read_snapshot"]("", "", 0, "") == 0

    def buffer(target: str, unread: int = 0) -> None:
        read(
            {
                "plugin_name": "irc",
                "first_line_not_read": unread,
                "localvar_name_00000": "type",
                "localvar_value_00000": "channel",
                "localvar_name_00001": "server",
                "localvar_value_00001": "libera",
                "localvar_name_00002": "channel",
                "localvar_value_00002": target,
            }
        )

    for index, tags in enumerate(["irc_privmsg", "irc_join", "irc_329,irc_numeric", ""]):
        buffer(f"#channel{index}")
        read({"last_read_line": 1, "date": 1789886614, "date_usec": 123999, "tags": tags})
    buffer("#trimmed", unread=1)
    read({"last_read_line": 0, "date": 1789886700, "date_usec": 0, "tags": "irc_privmsg"})
    script["finish_buffer"]()
    assert len(script["markers"]) == 4
    assert {marker["timestamp"] for marker in script["markers"]} == {"2026-09-20T06:43:34.123Z"}
    assert script["unread"] == [
        {"network": "libera", "target": "#trimmed", "scope": "retained_lines"}
    ]
    assert script["unresolved"] == []
