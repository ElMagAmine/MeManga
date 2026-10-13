"""
Crontab helpers for shell-safe construction of the Unix cron entry shared
by the CLI (`memanga cron install`) and the GUI Settings page.
"""

import shlex
from pathlib import Path, PurePosixPath

# Trailing shell comment that marks the crontab line `cron install` owns.
# install/remove/status only ever touch lines carrying it (issue #231).
MANAGED_MARKER = "# memanga-managed"


def quote_cron_path(path) -> str:
    """Quote a filesystem path for use inside a crontab command.

    ``shlex.quote()`` guards against spaces and shell metacharacters;
    crontab(5) additionally turns an unescaped ``%`` into a newline, so
    those are backslash-escaped on top of the shell quoting.
    """
    return shlex.quote(str(path)).replace("%", r"\%")


def build_cron_line(minute, hour, project_dir, python_path, config_dir=None) -> str:
    """Build the daily auto-check crontab entry with shell-safe paths.

    ``config_dir`` pins the scheduled run to a non-default config root
    (issue #221); None keeps the default location.
    """
    project_dir = PurePosixPath(Path(project_dir).as_posix())
    python_path = Path(python_path).as_posix()
    memanga = f"{quote_cron_path(python_path)} -m memanga"
    if config_dir is not None:
        memanga += f" --config-dir {quote_cron_path(Path(config_dir).as_posix())}"
    command = (
        f"cd {quote_cron_path(project_dir)} && "
        f"{memanga} check --auto --quiet"
    )
    log_path = quote_cron_path(project_dir / "memanga.log")
    return f"{minute} {hour} * * * {command} >> {log_path} 2>&1 {MANAGED_MARKER}"


def read_crontab(result):
    """Crontab text from a finished ``crontab -l`` run, or None if unreadable.

    A failed run counts as an empty crontab only when stderr says there is
    no crontab yet (cronie/vixie/macOS: "no crontab for USER"; busybox:
    "No such file or directory"). Any other failure returns None so
    callers never overwrite a crontab they could not read (issue #231).
    """
    if result.returncode == 0:
        return result.stdout or ""
    err = (result.stderr or "").lower()
    if "no crontab" in err or "no such file" in err:
        return ""
    return None


def is_managed_line(line: str) -> bool:
    """True for an active crontab line written by ``cron install``.

    Ownership comes only from the trailing marker (issue #231). Lines that
    merely mention MeManga, and commented-out lines, belong to the user.
    """
    stripped = line.strip()
    return (not stripped.startswith("#")
            and stripped.endswith(f" {MANAGED_MARKER}"))


def managed_lines(crontab: str) -> list:
    """The managed MeManga lines in ``crontab``."""
    return [line for line in crontab.splitlines() if is_managed_line(line)]


def unmanaged_memanga_lines(crontab: str) -> list:
    """Active lines that mention MeManga but lack the marker: hand-written
    jobs or entries from older installs. Reported, never modified."""
    return [line for line in crontab.splitlines()
            if "memanga" in line.lower() and not is_managed_line(line)
            and not line.lstrip().startswith("#")]


def remove_managed_lines(crontab: str):
    """Drop managed lines from ``crontab``, keeping every other line,
    blank line and comment as-is. Returns ``(new_text, removed_count)``."""
    kept, removed = [], 0
    for line in crontab.splitlines(keepends=True):
        if is_managed_line(line):
            removed += 1
        else:
            kept.append(line)
    return "".join(kept), removed


def replace_managed_line(crontab: str, cron_line: str) -> str:
    """Replace any managed lines in ``crontab`` with a single ``cron_line``
    appended at the end; unrelated entries are left untouched."""
    text, _ = remove_managed_lines(crontab)
    if text and not text.endswith("\n"):
        text += "\n"
    return f"{text}{cron_line}\n"
