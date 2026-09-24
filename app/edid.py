"""The EDID catalogue: what this matrix can hand an input.

Built by the poller on a cycle that actually reached the device — never at
startup. Nothing on the matrix path may fail a boot, and a catalogue cached
from a failed probe would publish an empty dropdown until somebody restarted
the pod by hand.

## Why the option strings are ours, not the device's

`edid_name` comes back from the device, and it is a bad identifier four ways:

- SYS 1-6 are all `'HDMI Matrix  '` — **with trailing spaces** — despite
  holding different content.
- SYS 9 and SYS 10 are both `UHD8K60`.
- USER 1 and USER 2 are byte-identical.
- It is parsed out of the EDID *content*, so writing a user slot with
  `@EDID-SET-USER` changes it. Options that churn between restarts break any
  automation holding the old string, with "Option is not valid".

So the option strings are constants here. The firmware's own `card.js`
`init_view()` hardcodes good names, index-aligned to SYS 1…10, and those are
what `_SYS_NAMES` below reproduces. User slots get plain `USER 1`…`USER 5`.
The device read then degrades to *validation* — it decides whether a slot
exists, and can no longer destabilise the entity.

Every label carries its index regardless, because a name alone is ambiguous on
this unit.

## What is deliberately not offered

`@EDID-SW-OUT` ("copy the EDID from output N") stays in the client API and out
of the entity. Copying from a sink means copying whatever that TV advertises —
from the Theater TV that would plausibly reintroduce the HDR/Dolby-Vision
metadata that is the whole reason this feature exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import structlog

from app.models import EdidSource

log = structlog.get_logger()

# Built-in slot names, index-aligned to SYS 1…10, taken from `init_view()` in
# the unit's own card.js rather than from `edid_name`.
_SYS_NAMES: tuple[str, ...] = (
    "HD8Stereo",
    "HD8DolbyDTS",
    "HD8Lossless",
    "HD12Stereo3D",
    "HD12DolbyDTS3D",
    "HD12Lossless3D",
    "UHD4K30",
    "UHD4K60",
    "UHD8K60",
    "UHD8K60_420",
)

# Bounded probe ranges. Fixed, not "walk until ERROR": a timeout is not an
# ERROR, and one dropped packet at slot 8 would silently drop
# `SYS 8 · UHD4K60`, the exact EDID this feature exists to select. Measured
# on this unit: sys 1-10 read, 11+ ERROR; user 1-5 read, 6 ERROR. The ranges
# are wider than that so a gap or an extra slot is still seen, but the probe
# skips anything above the write-side ceiling in `matrix_client.EDID_INDEX_MAX`
# — a slot we could read but not write must never become an option.
SYS_PROBE_RANGE = range(1, 17)
USER_PROBE_RANGE = range(1, 9)

_FAMILY_LABEL: dict[str, str] = {"sys": "SYS", "user": "USER"}


class _EdidReader(Protocol):  # pragma: no cover - typing only
    async def read_edid(self, source: EdidSource, index: int) -> dict | None:
        ...


@dataclass(frozen=True)
class EdidOption:
    """One selectable EDID.

    `device_name` is what the device reported, kept for diagnostics only. It
    is never part of `label`.
    """

    source: EdidSource
    index: int
    device_name: str | None = None

    @property
    def label(self) -> str:
        """The dropdown option. A code-owned constant, stable across restarts."""
        family = _FAMILY_LABEL.get(self.source, self.source.upper())
        if self.source == "sys" and 1 <= self.index <= len(_SYS_NAMES):
            return f"{family} {self.index} · {_SYS_NAMES[self.index - 1]}"
        return f"{family} {self.index}"


class EdidCatalogue:
    """Holds the probed options. Filled by the poller; read by the controller
    and the REST router.

    `loaded` stays False until a probe completed, so the poller retries on the
    next cycle rather than caching an empty catalogue forever.
    """

    def __init__(self) -> None:
        self._options: list[EdidOption] = []
        self._by_label: dict[str, EdidOption] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def options(self) -> list[EdidOption]:
        return list(self._options)

    @property
    def labels(self) -> list[str]:
        return [o.label for o in self._options]

    def resolve(self, label: str) -> EdidOption | None:
        """Map a dropdown option back to the slot it names."""
        return self._by_label.get(label.strip())

    def load(self, options: list[EdidOption]) -> None:
        self._options = list(options)
        self._by_label = {o.label: o for o in options}
        self._loaded = True
        log.info("edid_catalogue_loaded", count=len(options), labels=self.labels)

    async def build(self, matrix: _EdidReader) -> bool:
        """Probe the device and fill the catalogue. Returns True on success.

        Abandons the whole build on a transport failure (after one retry)
        rather than keeping a partial catalogue — a truncated dropdown is
        worse than none, because it looks complete.
        """
        if self._loaded:
            return True
        try:
            options = await probe_catalogue(matrix)
        except RuntimeError as exc:
            log.warning("edid_catalogue_probe_failed", error=str(exc))
            return False
        if not options:
            log.warning("edid_catalogue_probe_empty")
            return False
        self.load(options)
        return True


async def _read_with_one_retry(matrix: _EdidReader, source: EdidSource, index: int) -> dict | None:
    """Read a slot, retrying once on a transport failure.

    Propagates `RuntimeError` when the retry fails too, so the caller can
    abandon the build instead of mistaking a dropped packet for an absent slot.
    """
    try:
        return await matrix.read_edid(source, index)
    except RuntimeError as first:
        log.debug("edid_read_retry", source=source, index=index, error=str(first))
        return await matrix.read_edid(source, index)


async def probe_catalogue(matrix: _EdidReader) -> list[EdidOption]:
    """Validate each slot in a bounded range; absent slots are skipped.

    Does **not** stop at the first absent slot. Only the literal body `ERROR`
    means absent (`MatrixClient.read_edid` raises for everything else), so a
    gap in the middle is a real gap and a transport failure aborts the build.

    Raises:
        RuntimeError: If a slot could not be read even after one retry.
    """
    from app.matrix_client import EDID_INDEX_MAX  # local: avoid an import cycle

    options: list[EdidOption] = []
    for source, probe_range in (("sys", SYS_PROBE_RANGE), ("user", USER_PROBE_RANGE)):
        for index in probe_range:
            if index > EDID_INDEX_MAX[source]:
                # Readable but not writable — `set_input_edid` would reject it,
                # so it must never become an option.
                continue
            entry = await _read_with_one_retry(matrix, source, index)  # type: ignore[arg-type]
            if entry is None:
                continue
            options.append(
                EdidOption(
                    source=source,  # type: ignore[arg-type]
                    index=index,
                    device_name=(entry.get("name") or "").strip() or None,
                )
            )
    return options
