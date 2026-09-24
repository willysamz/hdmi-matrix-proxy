"""The EDID catalogue: what this matrix can hand an input, discovered at startup.

The matrix carries two families of stored EDIDs (`sys` built-ins and `user`
slots) plus the ability to copy the EDID read from any output. Their count is
per-unit, so we **probe** rather than hardcode: read slot 1, 2, 3 … and stop at
the first one the device answers `ERROR` to. On the unit in this house that
lands on SYS 1-10 and USER 1-5, but those are this unit's numbers.

Two things make the labels load-bearing:

- **A name is not an identifier.** SYS 1-6 are all named `HDMI Matrix` and yet
  hold different content, so a label of "HDMI Matrix" would be ambiguous and a
  user picking it would get an arbitrary one. Every label carries its index.
- **USER 3-5 hash-match SYS 3-5** on this unit, so the two families overlap.
  The content hash is kept so a human can tell which entries are duplicates.

Outputs are offered as `Copy from output N` with no name, because `out_edid`
returns `ERROR` on this unit and there is nothing to read.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

import structlog

from app.matrix_client import EDID_INDEX_MAX, EDID_PROBE_LIMIT
from app.models import EdidSource

log = structlog.get_logger()

# Published as the select's state until this proxy has set the input's EDID.
# HA's MQTT select maps the literal "None" to an unknown current_option, which
# is the only honest starting value: the assignment cannot be read back.
EDID_UNKNOWN_PAYLOAD = "None"

# The number of outputs whose EDID can be copied onto an input.
EDID_OUTPUT_COUNT = 8

# Families probed at startup, in the order they appear in the dropdown.
_PROBED_FAMILIES: tuple[EdidSource, ...] = ("sys", "user")

_FAMILY_LABEL: dict[str, str] = {"sys": "SYS", "user": "USER"}


class _EdidReader(Protocol):  # pragma: no cover - typing only
    async def read_edid(self, source: EdidSource, index: int) -> dict | None:
        ...


@dataclass(frozen=True)
class EdidOption:
    """One selectable EDID.

    `name` and `content_hash` are None for `out` options — `out_edid` cannot
    be read on this unit, so there is nothing to name or hash.
    """

    source: EdidSource
    index: int
    name: str | None = None
    content_hash: str | None = None

    @property
    def label(self) -> str:
        """The human-readable dropdown label. Always carries the index."""
        if self.source == "out":
            return f"Copy from output {self.index}"
        family = _FAMILY_LABEL.get(self.source, self.source.upper())
        name = (self.name or "").strip() or "unnamed"
        return f"{family} {self.index} · {name}"


class EdidCatalogue:
    """Probed once, then cached. The device's slot contents do not change at
    runtime unless somebody writes a USER slot, which is a front-panel act."""

    def __init__(self) -> None:
        self._options: list[EdidOption] = []
        self._by_label: dict[str, EdidOption] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        """True once a probe has found at least one readable slot.

        Stays False when the matrix was unreachable, so the next poll cycle
        retries rather than publishing an empty dropdown forever.
        """
        return self._loaded

    @property
    def options(self) -> list[EdidOption]:
        return list(self._options)

    @property
    def labels(self) -> list[str]:
        return [o.label for o in self._options]

    def resolve(self, label: str) -> EdidOption | None:
        """Map a dropdown label back to the option it names."""
        return self._by_label.get(label.strip())

    async def ensure_loaded(self, matrix: _EdidReader) -> None:
        """Probe the device once; a no-op on every call after a successful one."""
        if self._loaded:
            return
        options = await probe_catalogue(matrix)
        if not options:
            log.warning("edid_catalogue_probe_empty")
            return
        self._options = options
        self._by_label = {o.label: o for o in options}
        self._loaded = True
        log.info(
            "edid_catalogue_loaded",
            count=len(options),
            labels=[o.label for o in options],
        )


async def probe_catalogue(matrix: _EdidReader) -> list[EdidOption]:
    """Read each family from slot 1 upward, stopping at the first `ERROR`.

    Returns [] when nothing at all was readable — which is how an unreachable
    matrix looks, and the caller should retry rather than cache that.
    """
    options: list[EdidOption] = []
    for source in _PROBED_FAMILIES:
        for index in range(1, EDID_PROBE_LIMIT + 1):
            entry = await matrix.read_edid(source, index)
            if entry is None:
                # First ERROR in this family: that is the ceiling on this unit.
                break
            if index > EDID_INDEX_MAX[source]:
                # Readable but not writable: `MatrixClient.set_input_edid`
                # would reject it, so never offer it as an option. If this
                # ever fires, a unit has more slots than the write-side
                # ceiling in matrix_client.py knows about — raise that.
                log.warning(
                    "edid_slot_readable_but_above_write_ceiling",
                    source=source,
                    index=index,
                    write_ceiling=EDID_INDEX_MAX[source],
                )
                break
            hex_blob = entry.get("hex") or ""
            options.append(
                EdidOption(
                    source=source,
                    index=index,
                    name=entry.get("name"),
                    content_hash=hashlib.sha256(str(hex_blob).encode()).hexdigest()[:12],
                )
            )

    if not options:
        return []

    # Outputs are appended unconditionally: the copy-from-output command works
    # even though reading an output's EDID does not.
    options.extend(EdidOption(source="out", index=n) for n in range(1, EDID_OUTPUT_COUNT + 1))
    return options
