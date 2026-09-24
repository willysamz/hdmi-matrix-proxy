# Per-input EDID

The matrix advertises an EDID on each of its **inputs**, and a source reads that
EDID to decide what to send. Which EDID input 6 carries decides whether the PS5
sends HDR/Dolby Vision or plain SDR — and the multiviewer blanks on the former.
That is why this is in the proxy.

## The one thing to know first

**There is no way to read which EDID an input is currently using.** No endpoint
on this device reports the assignment. So the proxy cannot publish true state
for it, and an entity that looked authoritative would be lying.

The HA selects are therefore **write-through, not read-back**: `unknown` until
this proxy sets one, then whatever it set, published unretained so a restart
goes back to `unknown` rather than resurrecting a stale value. A change made at
the matrix's own web UI or front panel will not show up. The entity name says
`(not read back)` for exactly this reason.

## The device protocol

Commands go to `form-system-cmd.cgi` as `cmd=…`, the same endpoint `set_routing`
uses. No auth is needed for commands. (The web UI's login is `admin`/`admin`,
and logging in changes none of the behaviour below.)

| Command | Meaning |
|---|---|
| `@EDID-SW-OUT:<out>,<in>` | give input `<in>` the EDID read from output `<out>` |
| `@EDID-SW-SYS:<n>,<in>` | give input `<in>` built-in EDID `<n>` |
| `@EDID-SW-USER:<n>,<in>` | give input `<in>` user slot `<n>` |

`<in>` = `0` means **all inputs**. Inputs are 1-based.

Reads are POSTs to `form-system-info.cgi` returning `{"edid_name","edid_hex"}`:

| Param | Works? |
|---|---|
| `sys_edid=<n>` | yes, `n` = 1–10 on this unit; 11+ returns the literal body `ERROR` |
| `user_edid=<n>` | yes, at least 1–5 |
| `out_edid=<n>` | **`ERROR` on this unit**, logged in or not — not a permissions problem |

`MatrixClient.read_edid` returns `None` for an `ERROR` body rather than raising,
because a failed read is routine here.

The device answers `OK` to commands it then ignores, so **everything is
range-validated before it is sent**. An `OK` is not confirmation.

## The catalogue

Built by probing at startup: read slot 1, 2, 3 … per family and stop at the
first `ERROR`. The ceiling is not hardcoded — 10 and 5 are *this* unit's
numbers, not the model's. The probe does stop at `EDID_INDEX_MAX` in
`matrix_client.py`, which is the ceiling `set_input_edid` will accept: a slot we
could read but could not write is never offered, and hitting that cap logs
`edid_slot_readable_but_above_write_ceiling`.

Options are labelled `SYS 8 · UHD4K60`, `USER 1 · Beyond TV`,
`Copy from output 3`. **The index is part of the label** because a name is not
an identifier here: SYS 1–6 are all named `HDMI Matrix` while holding different
content, and USER 3–5 hash-match SYS 3–5.

Measured on this unit (2026-09-24):

| slot | name |
|---|---|
| SYS 1–6 | `HDMI Matrix` (1080p; distinct content despite one name) |
| SYS 7 | `UHD4K30` |
| SYS 8 | `UHD4K60` — plain 4K60, no HDR |
| SYS 9, 10 | `UHD8K60` |
| USER 1, 2 | `Beyond TV` — 4K60 + HDR + Dolby Vision + BT.2020 |
| USER 3–5 | `HDMI Matrix`, identical to SYS 3–5 |

## MQTT surface

| Topic | Direction |
|---|---|
| `matrix/edid/input/{1..8}/set` | HA → proxy, payload is a catalogue label |
| `matrix/edid/input/{1..8}/state` | proxy → HA, `None` or the label it last set (unretained) |

Discovery publishes one `select` per input at
`homeassistant/select/hdmi_matrix_input_{n}_edid/config`.

**There is no "all inputs" entity.** `MatrixClient.set_input_edid(..., input_num=None)`
sends the `,0` form for a human who wants it, but an accidental click in a
dashboard would retune every source in the house.

The controller does **not** trigger an immediate poll after an EDID write: the
poller reads routing state, and there is nothing to poll for EDID.

## Why input 6 needs this

Measured 2026-09-24 with the PS5 on input 6:

| EDID on input 6 | direct to a TV | through the multiviewer (single and quad) |
|---|---|---|
| `USER 1 · Beyond TV` (4K60 + HDR + DV) | 4K60 HDR/DV | **blank** |
| `SYS 8 · UHD4K60` (plain 4K60) | 4K60 SDR | works |
| `SYS 7 · UHD4K30` | 4K30 | works |
| `SYS 1 · HDMI Matrix` (1080p) | 1080p | works |

The cause is the HDR/Dolby-Vision metadata, not bandwidth and not HDCP — 4K60
passes fine without it. The older "output HDCP is 1.4" hypothesis is disproven:
both 1.4 and 2.2 blanked.

With the PS5's HDR set to **"On when supported"** the console follows the EDID,
so the swap alone produces the right behaviour with no console interaction. The
rule is **through the multiviewer or not**, not quad vs single.

A source only re-reads EDID on a hotplug, so a scene that changes the EDID
should then route the input away and back, or the change lands at some
arbitrary later time and looks flaky.
