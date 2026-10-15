"""Thin wrapper over the CUPS command-line client (lp, lpstat, cancel).

The commands talk to the server named by CUPS_SERVER (a host:port or the path of the
host's cups.sock). Every value that reaches an argv is validated first, so nothing
from a tool call can be read as an option.
"""

import os
import re
import subprocess
from typing import Any

_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@+-]{0,126}$")
_JOB = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.@+-]*)-(\d+)$")
SIDES = ("one-sided", "two-sided-long-edge", "two-sided-short-edge")
_TIMEOUT_S = 60


def check_printer_name(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"Invalid printer name: {name!r}")
    return name


def job_printer(job_id: str) -> str:
    """The printer a job id like 'Office-42' belongs to."""
    m = _JOB.match(job_id)
    if not m:
        raise ValueError(f"Invalid job id: {job_id!r} (expected <printer>-<number>)")
    return m.group(1)


class Cups:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        # The parsers below read the C locale's wording.
        self._env = {**(os.environ if env is None else env), "LANG": "C", "LC_ALL": "C"}

    def _run(self, *argv: str, stdin: bytes | None = None) -> str:
        try:
            p = subprocess.run(
                argv, input=stdin, capture_output=True, env=self._env, timeout=_TIMEOUT_S
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"CUPS client not installed: {argv[0]}") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"CUPS did not answer within {_TIMEOUT_S}s") from e
        out, err = p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
        if p.returncode != 0:
            raise RuntimeError(f"{argv[0]} failed: {(err or out).strip()[:300]}")
        return out

    def default_printer(self) -> str:
        out = self._run("lpstat", "-d")
        m = re.search(r"system default destination: (\S+)", out)
        return m.group(1) if m else ""

    def printers(self) -> list[dict[str, Any]]:
        try:
            states = self._run("lpstat", "-p")
            accepting = self._run("lpstat", "-a")
        except RuntimeError as e:
            if "No destinations added" in str(e):
                return []
            raise
        found: dict[str, dict[str, Any]] = {}
        last: dict[str, Any] | None = None
        for line in states.splitlines():
            m = re.match(r"^printer (\S+) (?:is (idle)|now (printing)|(disabled))", line)
            if m:
                state = m.group(2) or m.group(3) or m.group(4)
                last = found[m.group(1)] = {"name": m.group(1), "state": state, "accepting": False}
            elif line.startswith("\t") and last is not None and line.strip():
                # Indented lines carry the reason a printer is disabled.
                last["reason"] = line.strip()
        for line in accepting.splitlines():
            m = re.match(r"^(\S+) (not )?accepting requests", line)
            if m and m.group(1) in found:
                found[m.group(1)]["accepting"] = m.group(2) is None
        return list(found.values())

    def submit(
        self,
        pdf: bytes,
        printer: str,
        copies: int = 1,
        title: str = "",
        sides: str | None = None,
        media: str | None = None,
    ) -> str:
        """Queue a PDF read from stdin; returns the job id. media is a PAPER name."""
        argv = ["lp", "-d", check_printer_name(printer), "-n", str(int(copies))]
        if title:
            argv += ["-t", title.replace("\n", " ")[:200]]
        if sides:
            if sides not in SIDES:
                raise ValueError(f"sides must be one of {', '.join(SIDES)}")
            argv += ["-o", f"sides={sides}"]
        if media:
            argv += ["-o", f"media={media}"]
        out = self._run(*argv, stdin=pdf)
        m = re.search(r"request id is (\S+)", out)
        if not m:
            raise RuntimeError(f"lp gave no job id: {out.strip()[:200]}")
        return m.group(1)

    def jobs(self, printer: str | None = None, completed: bool = False) -> list[dict[str, Any]]:
        argv = ["lpstat", "-W", "completed" if completed else "not-completed", "-o"]
        if printer:
            argv.append(check_printer_name(printer))
        jobs = []
        for line in self._run(*argv).splitlines():
            m = re.match(r"^(\S+-\d+)\s+(\S+)\s+(\d+)\s+(.+?)\s*$", line)
            if m:
                jobs.append(
                    {
                        "job_id": m.group(1),
                        "printer": job_printer(m.group(1)),
                        "user": m.group(2),
                        "bytes": int(m.group(3)),
                        "submitted": m.group(4),
                    }
                )
        return jobs

    def cancel(self, job_id: str) -> None:
        job_printer(job_id)
        self._run("cancel", job_id)
