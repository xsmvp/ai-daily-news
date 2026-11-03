"""Runtime patch for twikit's X client-transaction hash lookup.

X changed the web bundle manifest from ``"ondemand.s":"<hash>"`` to two
separate id-keyed maps::

    {..., 59924:"ondemand.s", ...}          # id -> chunk name
    {..., 59924:"7ab12abd00dfc2b7", ...}    # id -> content hash

twikit 2.3.3 (latest, Feb 2025) still parses the old single-map form, so
``ClientTransaction.get_indices`` raises ``Couldn't get KEY_BYTE indices`` on
every request. The chunk itself and its indices are unchanged — only the hash
lookup broke, so we re-implement that one step.

Import for its side effect before creating a twikit ``Client``.
"""

import re

from twikit.x_client_transaction.transaction import (
    ClientTransaction,
    INDICES_REGEX,
)

_NAME_MAP_RE = re.compile(r'(\d{1,7}):"ondemand\.s"')
_HASH_MAP_RE = re.compile(r'(\d{1,7}):"([0-9a-f]{16})"')


async def _get_indices(self, home_page_response, session, headers):
    response = str(self.validate_response(home_page_response) or self.home_page_response)

    # twikit's original format (kept working in case X rolls it back)
    legacy = re.search(r"""['|"]ondemand\.s['|"]\s*:\s*['|"]([\w]*)['|"]""", response)
    if legacy and legacy.group(1):
        chunk_hash = legacy.group(1)
    else:
        name_hit = _NAME_MAP_RE.search(response)
        if not name_hit:
            raise Exception("Couldn't locate the ondemand.s chunk in the page source")
        chunk_id = name_hit.group(1)
        hash_hit = re.search(rf'{chunk_id}:"([0-9a-f]{{16}})"', response)
        if not hash_hit:
            raise Exception(f"Couldn't resolve the hash for chunk {chunk_id}")
        chunk_hash = hash_hit.group(1)

    url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{chunk_hash}a.js"
    chunk = await session.request(method="GET", url=url, headers=headers)

    indices = [m.group(2) for m in INDICES_REGEX.finditer(str(chunk.text))]
    if not indices:
        raise Exception("Couldn't get KEY_BYTE indices from ondemand.s chunk")

    indices = list(map(int, indices))
    return indices[0], indices[1:]


def apply():
    if getattr(ClientTransaction, "_patched_by_project", False):
        return
    ClientTransaction.get_indices = _get_indices
    ClientTransaction._patched_by_project = True
