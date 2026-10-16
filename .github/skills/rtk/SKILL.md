---
name: rtk
description: "Use when asked to use RTK, Rust Token Killer, or reduce terminal output with the rtk CLI. Verify availability and supported commands before using it."
---

# RTK CLI

Use RTK only as an optional terminal-output reducer; it is not required for the task.

1. Check availability using the platform's command lookup, then inspect `rtk --help` before relying on its syntax.
2. Use only subcommands documented by the installed version. Do not invent flags or assume every command is supported.
3. If RTK is unavailable, use the normal command and keep its output targeted. Do not install RTK unless the user asks.
4. Preserve the original command's meaning and exit status. Do not use output reduction for interactive prompts or when full output is needed to diagnose a failure.
5. Treat mutating commands with the same care and authorization as their ordinary equivalents.