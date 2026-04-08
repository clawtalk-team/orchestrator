"""Utility functions for the orchestrator service."""

import os
from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=1)
def get_git_sha() -> Optional[str]:
    """
    Get the current git commit SHA.

    Reads from the GIT_COMMIT environment variable that is set at build time
    in the Dockerfile. Falls back to None if not set.

    Returns:
        The git commit SHA (short format) if available, None otherwise.
    """
    git_commit = os.environ.get("GIT_COMMIT", "").strip()
    return git_commit if git_commit and git_commit != "unknown" else None
