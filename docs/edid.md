# Per-input EDID

The matrix advertises an EDID on each of its **inputs**, and a source reads that
EDID to decide what to send. Which EDID input 6 carries decides whether the PS5
sends HDR/Dolby Vision or plain SDR — and the multiviewer blanks on the former.
That is why this lives in the proxy.

## The one thing to know first

**There is no way to read which EDID an input is currently using.** No endpoint
on this device reports the assignment. So the proxy cannot publish true state
for it, and an entity that looked authoritative would be lying.

The HA select therefore shows **what was set, not what the device reports**. It
is named `... EDID (set, not read back)`. State is published **retained** and
nothing is published at boot, so the broker replays the last value — no storage,
same as the routing selects. A change made at the matrix's own web UI or front
panel will not appear.

The read-back that *does* exist sits beside it:
`sensor.<device>_input_N_resolution`, from `in_info`. That is not which EDID an
input carries but the resolution the source settled on after reading it — the
measured effect, and the visible signal when the select has gone stale. It is
what the 2026-09-24 diagnosis actually watched.

## The device protocol

Commands go to `form-system-cmd.cgi` as `cmd=…`, the same endpoint `set_routing`
uses. No auth is needed for commands. (The web UI's login is `admin`/`admin`,
and logging in changes none of the behaviour below.)

| Command | Meaning |
|---|---|
| `@EDID-SW-OUT:<out>,<in>` | give input `<in>` the EDID read from output `<out>` |
| `@EDID-SW-SYS:<n>,<in>` | give input `<in>` built-in EDID `<n>` |
| `@EDID-SW-USER:<n>,<in>` | give input `<in>` user slot `<n>` |
| `@PORT-RESET:0,<NN>` | reset input port `<NN>` (see the re-handshake below) |

`<in>` = `0` means **all inputs**; inputs are otherwise 1-based, and the proxy
rejects a literal `0` rather than treating it as that sentinel. `@EDID-SW-*`
indices and inputs are **raw and unpadded**; `@PORT-RESET`'s port is **1-based
zero-padded to two digits**. Do not cross the two formats.

Reads are POSTs to `form-system-info.cgi`:

| Param | Behaviour |
|---|---|
| `sys_edid=<n>` | 1–10 return `{"edid_name","edid_hex"}`; 11+ return the literal body `ERROR` |
| `user_edid=<n>` | 1–5 return; 6+ return `ERROR` |
| `out_edid=<n>` | **`ERROR` on this unit**, logged in or not — not a permissions problem |
| `in_info=<n-1>` | **0-based.** `{"in_info":{"InputResolution","Hpd","BoardType",…}}` |

Index `0` returns valid JSON with an empty name, so reads start at 1 and a slot
counts as present only when both `edid_name` and `edid_hex` are non-empty.

**A failed read is not the same as an absent slot**, and conflating them is how
a catalogue silently loses an entry:

- literal body `ERROR` → absent → `read_edid` returns `None`
- an unrecognised parameter returns a 4-byte non-JSON body → **raises**
- a timeout or connection error → **raises**

The device answers `OK` to commands it then ignores, so **ranges are validated
before sending and the response body is checked after**. `set_input_edid`
returns True only when the body was `OK`; the MQTT controller publishes state
only on that, and the REST endpoint reports `success: false` otherwise.

Multi-request operations (the catalogue build, set + re-handshake) are
serialised by an `asyncio.Lock` on the client. httpx is concurrency-safe; the
matrix is the concern — its own UI throttles polling around writes.

## The catalogue

**Built by the poller**, on a cycle that actually reached the device — never at
startup. Every matrix call on the boot path swallows its errors and falls back,
a probe costs roughly 260 ms per slot in front of the readiness probe, and an
unreachable matrix would otherwise either crash-loop the pod or freeze an empty
dropdown in place. If a build fails it is simply retried next cycle.

The probe walks a **bounded range** (sys 1–16, user 1–8, capped at the
write-side ceiling) and does **not** stop at the first absent slot. Stopping
would mean one dropped packet at slot 8 silently dropping `SYS 8 · UHD4K60`,
the exact EDID this feature exists to select. A read that fails is retried once
and then abandons the whole build — a truncated catalogue is worse than none,
because it looks complete.

**The option strings are code-owned constants, never the device's `edid_name`.**
That string is a bad identifier four ways: SYS 1–6 are all `'HDMI Matrix  '`
with trailing spaces despite distinct content; SYS 9 and 10 are both
`UHD8K60`; USER 1 and 2 are byte-identical; and it is parsed from EDID content,
so an `@EDID-SET-USER` write changes it and the options would churn across
restarts, breaking any automation holding the old string with "Option is not
valid". The names come from the firmware's own `card.js` `init_view()` table,
index-aligned to SYS 1…10:

| slot | option | slot | option |
|---|---|---|---|
| SYS 1 | `SYS 1 · HD8Stereo` | SYS 6 | `SYS 6 · HD12Lossless3D` |
| SYS 2 | `SYS 2 · HD8DolbyDTS` | SYS 7 | `SYS 7 · UHD4K30` |
| SYS 3 | `SYS 3 · HD8Lossless` | SYS 8 | `SYS 8 · UHD4K60` |
| SYS 4 | `SYS 4 · HD12Stereo3D` | SYS 9 | `SYS 9 · UHD8K60` |
| SYS 5 | `SYS 5 · HD12DolbyDTS3D` | SYS 10 | `SYS 10 · UHD8K60_420` |

User slots are plain `USER 1`…`USER 5`. The device read degrades to
*validation*: it decides whether a slot exists and can no longer destabilise the
entity. Whatever the device reported is kept as `device_name` for diagnostics
and never appears in a label.

**`@EDID-SW-OUT` is not offered as an option.** It stays in the client API and
in the REST body, out of the entity: copying the EDID from an output means
copying whatever that TV advertises, and from the Theater TV that would
plausibly reintroduce the HDR/Dolby-Vision metadata at the root of this problem.

## The re-handshake, and what is not known about it

A source only re-reads EDID on a hotplug, so an EDID change needs *something* to
make it look again. **The proxy owns that**, not the caller and not an HA
automation: it is the only layer that knows an EDID just changed and on which
input. After a confirmed assignment `set_input_edid` sends `@PORT-RESET:0,<NN>`
for that input — the same command the unit's own UI sends from the reset button
on the input setup page (`card.js`, `$(".reset-in")`).

**Treat this as unverified.** Specifically:

- It is **not established that a re-handshake is required at all.** Every
  successful hardware test on 2026-09-24 reflexively re-routed the affected
  output away and back after the EDID write, so the EDID change was never
  observed on its own. It may well take effect immediately.
- That re-route is **not an obvious mechanism.** EDID is presented to the source
  on the *input* port; changing which input feeds an output should not make a
  source re-read anything. Either the matrix pulses HPD on an input when its
  routing changes, or the re-route did nothing.
- `@PORT-RESET` is used instead because it is input-scoped: it perturbs no
  routing, so it publishes no intermediate source over MQTT for the live
  source-watching automation to react to, which a route-bounce would. It has
  **never been sent to this hardware**, and the web UI blanks that port's
  audio-select, mirror and picture sliders straight afterwards, which hints it
  may reset more of the input card's configuration than the hotplug line.

It is structurally optional: `settings.matrix_edid_rehandshake`
(`MATRIX_EDID_REHANDSHAKE`, default on) is the single place to turn it off, and
the REST body takes `"rehandshake": false` per call. The all-inputs form never
re-handshakes, because that would reset all eight ports at once.

### Redundant sets are cheap

Scenes set the EDID explicitly *and* an HA automation watches the selects, to
minimise blank-screen time, so the same value arrives twice on purpose. The MQTT
controller remembers what it last set per input and, on a repeat, skips both the
write and the re-handshake while still re-publishing state. This matters: a port
reset drops video for a moment, so a redundant call that re-handshaked would
cause the very blink the belt-and-braces approach exists to avoid.

That memory is per-process and empty after a restart, so the first set following
a restart always writes even though the broker replayed the old value. The REST
endpoint does not dedupe — it does exactly what it is told.

## Surfaces

REST (what the house's scenes use — every matrix script is a
`rest_command.matrix_*` against this proxy):

| Endpoint | |
|---|---|
| `GET /api/edid` | the catalogue; probes on demand if nothing has built it |
| `POST /api/edid` | `{"source":"sys","index":8,"input":6,"rehandshake":true}` |

`input` is required and 1–8. There is no all-inputs form over REST.

MQTT:

| Topic | Direction |
|---|---|
| `matrix/edid/input/{1..8}/set` | HA → proxy, payload is a catalogue label |
| `matrix/edid/input/{1..8}/state` | proxy → HA, the label it last set (retained) |
| `matrix/edid/input/{1..8}/resolution` | proxy → HA, live input resolution (retained) |

Discovery publishes one `select` and one `sensor` per input, at
`homeassistant/select/hdmi_matrix_input_{n}_edid/config` and
`homeassistant/sensor/hdmi_matrix_input_{n}_resolution/config`. **There is no
"all inputs" entity** — `MatrixClient.set_input_edid(..., input_num=None)` sends
the `,0` form for a human who wants it, but an accidental click would retune
every source in the house.

The controller does **not** trigger an immediate poll after an EDID write: the
poller reads routing state, and there is nothing to poll for EDID.

## Why input 6 needs this

Measured 2026-09-24 with the PS5 on input 6:

| EDID on input 6 | direct to a TV | through the multiviewer (single and quad) |
|---|---|---|
| `USER 1` "Beyond TV" (4K60 + HDR + DV) | 4K60 HDR/DV | **blank** |
| `SYS 8 · UHD4K60` (plain 4K60) | 4K60 SDR | works |
| `SYS 7 · UHD4K30` | 4K30 | works |
| `SYS 1` (1080p) | 1080p | works |

The cause is the HDR/Dolby-Vision metadata, not bandwidth and not HDCP — 4K60
passes fine without it. The older "output HDCP is 1.4" hypothesis is disproven:
both 1.4 and 2.2 blanked.

With the PS5's HDR set to **"On when supported"** the console follows the EDID,
so the swap alone produces the right behaviour with no console interaction. The
rule is **through the multiviewer or not**, not quad vs single.
