"""The web surfaces an install serves: the Console at / and /console, the remote at
/remote.

What the Console contains depends on the install - one curating a library and one
running games do not need the same screens. The remote is the same install seen from a
phone, and it is a second shell rather than the same one narrowed: a workbench is a list
beside an inspector, and one hand cannot hold two panes.
"""

from __future__ import annotations


def register() -> None:
    """Import the page modules so their @ui.page decorators register the routes."""
    from console import page, remote  # noqa: F401
