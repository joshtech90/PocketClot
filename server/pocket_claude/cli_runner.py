"""Run a configured research CLI with bounded JSON output and isolated state."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from collections.abc import Mapping, Sequence
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 20.0


class CliError(Exception):
    def __init__(self, message: str, *, returncode: int | None = None):
        super().__init__(message)
        self.returncode = returncode


def executable_path(value: str) -> Path | None:
    if not value or "\x00" in value:
        return None
    path = Path(value)
    return path if path.is_absolute() and path.is_file() and os.access(path, os.X_OK) else None


async def read_json(
    executable: Path,
    arguments: Sequence[str],
    *,
    state_dir: Path,
    environment: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_stdout_bytes: int = 256 * 1024,
) -> object:
    """Arguments and extra environment come from the provider adapter."""
    if not executable.is_absolute():
        raise CliError("Der CLI-Pfad muss absolut sein.")
    try:
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if state_dir.is_symlink():
            raise OSError("CLI state directory is a symlink")
        state_dir.chmod(0o700)
        proc = await asyncio.create_subprocess_exec(
            str(executable), *arguments,
            cwd=state_dir,
            env={**(environment or {}), "HOME": str(state_dir),
                 "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        raise CliError("Das Werkzeug konnte nicht gestartet werden.") from exc

    async def read_output() -> bytes:
        assert proc.stdout is not None
        output = bytearray()
        while chunk := await proc.stdout.read(16 * 1024):
            output.extend(chunk)
            if len(output) > max_stdout_bytes:
                raise CliError("Die Antwort des Werkzeugs war zu groß.")
        await proc.wait()
        return bytes(output)

    async def drain_and_reap() -> None:
        assert proc.stdout is not None
        while await proc.stdout.read(16 * 1024):
            pass
        await proc.wait()

    try:
        output = await asyncio.wait_for(read_output(), timeout_seconds)
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise CliError("Die Abfrage hat zu lange gedauert.") from exc
    finally:
        # A child can still hold stdout open after the CLI itself has exited.
        if proc.returncode is None or (proc.stdout is not None and not proc.stdout.at_eof()):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            try:
                await asyncio.wait_for(drain_and_reap(), 2)
            except (TimeoutError, asyncio.TimeoutError):
                # A detached descendant can hold stdout open. asyncio's
                # Process exposes no public method to close its pipe reader.
                proc._transport.close()

    if proc.returncode:
        raise CliError("Das Werkzeug hat die Abfrage abgebrochen.", returncode=proc.returncode)
    try:
        return json.loads(output)
    except (ValueError, RecursionError) as exc:
        raise CliError("Das Werkzeug hat ungültige Daten geliefert.") from exc
