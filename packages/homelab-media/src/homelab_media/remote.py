"""Transparent SSH remote dispatcher for running homelab-media on the storage host."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homelab_media.config import MediaConfig

SSH_BASE_OPTS: tuple[str, ...] = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=5")
REMOTE_WORKSPACE = "$HOME/dotfiles/packages"


def dispatch_remote(config: MediaConfig, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute `media <args>` on the homelab storage host over SSH.

    Requires ~/dotfiles/packages/homelab-media to exist on the remote host.
    """
    ssh_bin = shutil.which("ssh") or "ssh"
    target = f"{config.ssh_user}@{config.homelab_host}"
    quoted_args = " ".join(shlex.quote(a) for a in args)

    is_tty = sys.stdout.isatty()
    tty_env = f"FORCE_COLOR=1 COLUMNS={shutil.get_terminal_size().columns} " if is_tty else ""
    if is_tty and (ls_colors := os.environ.get("LS_COLORS")):
        tty_env += f"LS_COLORS={shlex.quote(ls_colors)} "
    remote_cmd = (
        f"if [ ! -d {REMOTE_WORKSPACE}/homelab-media ]; then "
        f"echo 'homelab-media not found at {REMOTE_WORKSPACE}/homelab-media on {config.homelab_host}. "
        f"Sync/pull ~/dotfiles on {config.homelab_host} first.' >&2; exit 2; fi; "
        f"PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:$PATH "
        f"HOMELAB_MEDIA_LOCAL=1 {tty_env}"
        f"uv run --quiet --directory {REMOTE_WORKSPACE} media {quoted_args}"
    )

    env = os.environ.copy()
    return subprocess.run(  # noqa: S603
        [ssh_bin, *SSH_BASE_OPTS, target, remote_cmd],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
