"""Converting a library from another frontend into game folders.

It only ever creates. A foreign layout is read and turned into entries of ours; nothing
of the source is written to, and nothing already in the library is changed. That is what
makes it the right first extension: a failed import leaves both libraries exactly as
they were.

Built as an extension deliberately, with no privileged access - the same manifest, the
same scopes and the same context an outside author is given. Where it cannot do
something through them, the contract is short and that is worth finding out.
"""

from __future__ import annotations

from . import pinballx

# Every source this build can read. A reader answers `detect` and `read` and knows
# nothing of ours - the mapping from what it found to what we store is the importer's,
# and happens once.
READERS = (pinballx,)


def register(ctx) -> None:
    ctx.logger.info("%s readers available", len(READERS))
