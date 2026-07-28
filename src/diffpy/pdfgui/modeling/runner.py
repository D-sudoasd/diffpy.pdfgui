"""Controlled process execution for external PDF modeling engines."""

from __future__ import annotations

import math
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import BinaryIO

from diffpy.pdfgui.modeling.models import BackendStatus, ExecutionResult

_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
_ENVIRONMENT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TRUNCATION_SUFFIX = b"\n<output truncated by PDFgui>\n"


class BackendExecutionError(RuntimeError):
    """Raised when an external backend command cannot be constructed safely."""


def run_external_backend(
    status: BackendStatus,
    arguments: Sequence[str],
    *,
    working_directory: str | Path | None = None,
    timeout: float = 3600.0,
    extra_environment: Mapping[str, str] | None = None,
) -> ExecutionResult:
    """Run a registered external backend without shell interpretation."""

    command = _build_command(status, arguments)
    cwd = _validated_working_directory(working_directory)
    seconds = _validated_timeout(timeout)
    environment = _validated_environment(extra_environment)
    try:
        with tempfile.TemporaryFile() as stdout_stream, tempfile.TemporaryFile() as stderr_stream:
            try:
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    env=environment,
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    timeout=seconds,
                    check=False,
                    shell=False,
                )
                return_code = completed.returncode
                timed_out = False
            except subprocess.TimeoutExpired:
                return_code = -9
                timed_out = True
            stdout, stdout_truncated = _read_bounded_output(stdout_stream)
            stderr, stderr_truncated = _read_bounded_output(stderr_stream)
    except (FileNotFoundError, PermissionError, OSError) as error:
        raise BackendExecutionError(f"could not launch {status.display_name}: {error}") from error
    return ExecutionResult(
        backend_id=status.backend_id,
        command=tuple(command),
        working_directory=cwd,
        return_code=return_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        output_truncated=stdout_truncated or stderr_truncated,
    )


def _build_command(status: BackendStatus, arguments: Sequence[str]) -> list[str]:
    if status.backend_id == "rmcprofile":
        executable = status.executable
    elif status.backend_id == "fullrmc":
        executable = status.python_executable
    else:
        raise BackendExecutionError(
            f"backend {status.backend_id!r} is not registered for external process execution"
        )
    if not status.usable or not executable:
        raise BackendExecutionError(f"backend {status.display_name} is not available")
    command = [executable]
    for argument in arguments:
        try:
            path_value = os.fspath(argument)
        except TypeError as error:
            raise BackendExecutionError("command arguments must be strings or paths") from error
        if isinstance(path_value, bytes):
            raise BackendExecutionError("command arguments must use text, not bytes")
        if "\x00" in path_value:
            raise BackendExecutionError("command arguments cannot contain null bytes")
        command.append(path_value)
    if len(command) == 1:
        raise BackendExecutionError("external backend arguments are required")
    return command


def _validated_working_directory(value: str | Path | None) -> str:
    path = Path.cwd() if value is None else Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise BackendExecutionError(f"working directory does not exist: {path}") from error
    if not resolved.is_dir():
        raise BackendExecutionError(f"working directory is not a directory: {resolved}")
    return str(resolved)


def _validated_timeout(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as error:
        raise BackendExecutionError("timeout must be numeric") from error
    if not math.isfinite(timeout) or timeout < 1.0 or timeout > 86400.0:
        raise BackendExecutionError("timeout must be finite and between 1 and 86400 seconds")
    return timeout


def _validated_environment(extra: Mapping[str, str] | None) -> dict[str, str]:
    environment = os.environ.copy()
    if extra is None:
        return environment
    if len(extra) > 64:
        raise BackendExecutionError("at most 64 environment overrides are allowed")
    for key, value in extra.items():
        key_text = str(key)
        value_text = str(value)
        if not _ENVIRONMENT_KEY.fullmatch(key_text):
            raise BackendExecutionError(f"invalid environment variable name: {key_text!r}")
        if "\x00" in value_text:
            raise BackendExecutionError("environment values cannot contain null bytes")
        environment[key_text] = value_text
    return environment


def _read_bounded_output(stream: BinaryIO) -> tuple[str, bool]:
    stream.flush()
    stream.seek(0)
    payload = stream.read(_MAX_OUTPUT_BYTES + 1)
    truncated = len(payload) > _MAX_OUTPUT_BYTES
    if truncated:
        keep = _MAX_OUTPUT_BYTES - len(_TRUNCATION_SUFFIX)
        payload = payload[:keep] + _TRUNCATION_SUFFIX
    return payload.decode("utf-8", errors="replace"), truncated
