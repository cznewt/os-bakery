"""Provisioner backends — concrete implementations of `_mount_and_provision`.

Each backend exports a ``provision(ctx) -> bool`` returning True if it handled
the build, False if the caller should try the next backend (or fall through
to a no-op).
"""
