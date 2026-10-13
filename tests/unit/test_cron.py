"""Tests for memanga.cron shell-safe crontab line construction (#109)."""

import shlex
import subprocess

from memanga.cron import (
    MANAGED_MARKER,
    build_cron_line,
    is_managed_line,
    managed_lines,
    quote_cron_path,
    read_crontab,
    remove_managed_lines,
    replace_managed_line,
    unmanaged_memanga_lines,
)


class TestQuoteCronPath:
    def test_plain_path_unchanged(self):
        assert quote_cron_path("/opt/memanga") == "/opt/memanga"

    def test_path_with_spaces_is_quoted(self):
        assert quote_cron_path("/opt/My Manga") == "'/opt/My Manga'"

    def test_shell_metacharacters_neutralized(self):
        evil = "/tmp/$(touch pwned); echo"
        assert shlex.split(quote_cron_path(evil)) == [evil]

    def test_percent_escaped_for_cron(self):
        # crontab(5) turns an unescaped % into a newline.
        assert quote_cron_path("/opt/100%manga") == r"/opt/100\%manga"


class TestBuildCronLine:
    def test_plain_paths(self):
        line = build_cron_line(0, 6, "/opt/memanga", "/usr/bin/python3")
        assert line == (
            "0 6 * * * cd /opt/memanga && /usr/bin/python3 "
            "-m memanga check --auto --quiet >> /opt/memanga/memanga.log 2>&1 "
            "# memanga-managed"
        )

    def test_paths_with_spaces(self):
        line = build_cron_line(30, 7, "/opt/My Manga",
                               "/opt/My Manga/venv/bin/python3")
        assert line == (
            "30 7 * * * cd '/opt/My Manga' && "
            "'/opt/My Manga/venv/bin/python3' "
            "-m memanga check --auto --quiet "
            ">> '/opt/My Manga/memanga.log' 2>&1 # memanga-managed"
        )

    def test_config_dir_is_passed_to_scheduled_check(self):
        line = build_cron_line(0, 6, "/opt/memanga", "/usr/bin/python3",
                               config_dir="/srv/My Manga/config")
        command = line.split("* * * ", 1)[1]
        assert shlex.split(command)[3:9] == [
            "/usr/bin/python3", "-m", "memanga",
            "--config-dir", "/srv/My Manga/config", "check",
        ]

    def test_metacharacter_paths_stay_single_words(self):
        evil = "/tmp/x; touch pwned"
        line = build_cron_line(0, 6, evil, "/usr/bin/python3")
        command = line.split("* * * ", 1)[1]
        # The shell must see the whole path as one word, not extra commands.
        assert evil in shlex.split(command)

    def test_marker_is_a_shell_comment(self):
        """The marker must not reach the scheduled command (#231)."""
        line = build_cron_line(0, 6, "/opt/memanga", "/usr/bin/python3")
        command = line.split("* * * ", 1)[1]
        assert shlex.split(command, comments=True)[-1] == "2>&1"
        assert line.endswith(" " + MANAGED_MARKER)


MANAGED = build_cron_line(0, 6, "/opt/memanga", "/usr/bin/python3")
LEGACY = ("0 6 * * * cd /opt/memanga && /usr/bin/python3 -m memanga check "
          "--auto --quiet >> /opt/memanga/memanga.log 2>&1")
DOCKER = "0 5 * * * docker compose -f /srv/memanga/compose.yaml run --rm memanga check"
CRONTAB = (
    "# backups\n"
    "MAILTO=me@example.com\n"
    "\n"
    "30 2 * * *  /usr/local/bin/backup.sh   # nightly\n"
    f"{LEGACY}\n"
    "\n"
    f"{DOCKER}\n"
)


class TestManagedLines:
    """#231: only the marked line belongs to `cron install`."""

    def test_detection(self):
        assert is_managed_line(MANAGED)
        assert is_managed_line(MANAGED + "\n")
        assert not is_managed_line(LEGACY)
        assert not is_managed_line(DOCKER)
        assert not is_managed_line("# " + MANAGED)
        assert not is_managed_line("")

    def test_managed_lines(self):
        assert managed_lines(CRONTAB) == []
        assert managed_lines(CRONTAB + MANAGED + "\n") == [MANAGED]

    def test_unmanaged_memanga_lines(self):
        assert unmanaged_memanga_lines(CRONTAB + MANAGED + "\n") == [LEGACY, DOCKER]

    def test_remove_keeps_everything_else_byte_for_byte(self):
        text = CRONTAB.replace("\n\n", f"\n{MANAGED}\n\n", 1)
        new, removed = remove_managed_lines(text)
        assert removed == 1
        assert new == CRONTAB

    def test_remove_without_managed_line_is_a_no_op(self):
        assert remove_managed_lines(CRONTAB) == (CRONTAB, 0)
        assert remove_managed_lines("") == ("", 0)

    def test_replace_appends_to_untouched_crontab(self):
        assert replace_managed_line(CRONTAB, MANAGED) == CRONTAB + MANAGED + "\n"

    def test_replace_swaps_previous_managed_line(self):
        old = build_cron_line(15, 3, "/opt/memanga", "/usr/bin/python3")
        new = replace_managed_line(f"{old}\n{CRONTAB}{old}\n", MANAGED)
        assert new == CRONTAB + MANAGED + "\n"

    def test_replace_handles_missing_trailing_newline(self):
        assert replace_managed_line("", MANAGED) == MANAGED + "\n"
        assert replace_managed_line(DOCKER, MANAGED) == f"{DOCKER}\n{MANAGED}\n"


class TestReadCrontab:
    """#231: only a real "no crontab" failure counts as an empty crontab."""

    @staticmethod
    def _result(returncode, stdout="", stderr=""):
        return subprocess.CompletedProcess(["crontab", "-l"], returncode,
                                           stdout, stderr)

    def test_success_returns_text(self):
        assert read_crontab(self._result(0, CRONTAB)) == CRONTAB

    def test_no_crontab_is_empty(self):
        for err in ("no crontab for alice\n",
                    "crontab: no crontab for alice\n",
                    "crontab: can't open 'alice': No such file or directory\n"):
            assert read_crontab(self._result(1, stderr=err)) == ""

    def test_other_failures_are_unreadable(self):
        assert read_crontab(self._result(1)) is None
        assert read_crontab(self._result(
            1, stderr="crontab: Permission denied\n")) is None
