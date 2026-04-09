from __future__ import annotations

import shlex


class SafetyViolation(Exception):
    pass


ALLOWED_COMMAND_PREFIXES = {
    "cat",
    "echo",
    "file",
    "find",
    "grep",
    "head",
    "ls",
    "pwd",
    "printf",
    "rg",
    "sed",
    "stat",
    "tail",
    "wc",
}

BLOCKED_SHELL_PATTERNS = ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n", "\r")

BLOCKED_ARGUMENTS_BY_COMMAND = {
    "find": {"-delete", "-exec", "-execdir", "-ok", "-okdir"},
    "sed": {"-i", "--in-place"},
}


def _validate_arguments(parts: list[str]) -> None:
    command = parts[0]
    blocked_arguments = BLOCKED_ARGUMENTS_BY_COMMAND.get(command, set())
    for argument in parts[1:]:
        if argument in blocked_arguments:
            raise SafetyViolation(f"Command '{command}' cannot be run with argument '{argument}'.")
        if command == "sed" and argument.startswith("-i"):
            raise SafetyViolation("Command 'sed' cannot be run with in-place editing enabled.")


def validate_shell_command(command: str) -> list[str]:
    if any(pattern in command for pattern in BLOCKED_SHELL_PATTERNS):
        raise SafetyViolation("Shell metacharacters are blocked by the safety policy.")
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise SafetyViolation(f"Command could not be parsed safely: {exc}") from exc
    if not parts:
        raise SafetyViolation("Refusing to execute an empty shell command.")
    if parts[0] not in ALLOWED_COMMAND_PREFIXES:
        raise SafetyViolation(f"Command '{parts[0]}' is not in the low-risk allowlist.")
    _validate_arguments(parts)
    return parts
