# Should we MQTT-ify `hdmi-matrix-proxy`? — recommendation + migration outline

## Short answer

**Yes**, with a transition period. Net wins are real and large:
- **~315 lines of HA config disappear** (46% of `configuration.yaml`).
- **Consistency** with the PDU bridge + Frigate + future MQTT producers.
- **Lower change-cost** when adding/renaming inputs or outputs (today every change touches 4+ places).
- **Lower latency** on routing state — push instead of 10 s poll.

Cost: ~2–3 h to MQTT-enable the proxy (copy the PDU pattern), then a
few more hours of HA-side migration that has to be done carefully
because dashboards + automations + scripts all reference the
existing REST-derived entity_ids.

## Today (REST-only)

`hdmi-matrix-proxy` is a FastAPI service. Three routers
(`health`, `system`, `routing`) expose ~10 endpoints. State is
poll-only — there's a 30 s `_health_monitor` background task in
`app/matrix_client.py:330` but no MQTT or push.

HA consumes it through **315 lines** of `configuration.yaml`:

| HA config block | Lines | Count | Polling |
|---|---|---|---|
| REST sensors (`/api/inputs`, `/api/outputs`, `/api/routing`, `/api/status`, `/healthz/ready`) | 72–128 | 5 | every 10–300 s |
| `rest_command` entries (`matrix_route`, 8× per-output, `matrix_preset`) | 214–278 | 10 | n/a |
| `input_select.matrix_output_{1..8}_source` | 365–407 | 8 | n/a |
| Template sensors (`Matrix Output {1..8} Current Source`) | 489–657 | 8 | derived |
| **Total** | **~315 lines** | **31 entities** | tightest poll = 10 s on `/api/routing` |

Plus references in `lovelace.hdmi_matrix`, `lovelace.multi_viewer`,
and at least 2 archived dashboard variants.

## After (MQTT discovery + push)

Mirror the `cyberpower-pdu-mqtt-bridge` pattern. The proxy gets:
- `app/mqtt_client.py` — aiomqtt wrapper.
- `app/discovery.py` — emits retained `homeassistant/+/+/config` payloads at startup for sensors + selects + buttons.
- `app/poller.py` — moves the existing routing-poll cadence (10 s) into the proxy itself; publishes `matrix/routing/output{N}/state` deltas to MQTT.
- `app/controller.py` — subscribes to `matrix/routing/output{N}/set`, calls the existing matrix client to flip the route.
- Same REST endpoints stay in place (additive, not replacement) for debugging + scripts.

HA side becomes:
```yaml
# (nothing — the MQTT integration auto-creates everything)
```

Entities HA gets via discovery:
| What | Type | Source |
|---|---|---|
| `select.matrix_output_{1..8}_source` | `select` | discovery + retained state |
| `sensor.matrix_output_{1..8}_current_source` | sensor (same as today) | discovery |
| `binary_sensor.hdmi_matrix_health` | `binary_sensor` | health monitor |
| `sensor.hdmi_matrix_status` | sensor | health monitor |

Net entity count is the same; the **config burden goes from 315 lines to 0**.

## Pros, weighed

1. **Maintenance.** Today adding a 9th output (or renaming "Output 3" → "Bedroom TV") means: update proxy, restart, then edit configuration.yaml in 4 places (REST sensor, rest_command, input_select, template). With MQTT discovery: update proxy, restart. Done.
2. **Consistency.** PDU + Frigate already on MQTT; broker is already deployed. Matrix is the last REST-poll outlier in the homelab.
3. **Latency.** Routing state pushes in <1 s instead of waiting on HA's 10 s scan_interval.
4. **Lower coupling.** Today HA contains business logic ("derive 'current source' for output N from `state_attr('sensor.hdmi_matrix_routing', 'outputs')`"). The 160-line template-sensor block exists because we can't get nicely-shaped state out of REST. With MQTT, the proxy publishes the shape HA wants.
5. **Dashboards become trivial.** Today's `lovelace.hdmi_matrix` is mostly stitching together template sensors + input_selects + rest_commands. With `select` entities you get one card per output, native UX.

## Cons / risks

1. **HA migration friction.** Existing dashboards reference `input_select.matrix_output_3_source`, `sensor.matrix_output_3_current_source`, etc. New MQTT-discovered entities will be named differently unless we set `object_id` explicitly via discovery to preserve them. We have to pin discovery `object_id`/`unique_id` so entity_ids don't change — possible but takes care.
2. **Cycle of "I'll just keep both"** trap. Easy to leave the REST sensors in place "just in case" and never finish the migration. We should set a deadline.
3. **The matrix-poll rate doesn't go away.** Someone has to poll the matrix for state. Today HA does it at 10 s; tomorrow the proxy does it at 10 s. Hardware impact identical; just centralized. Not a benefit, but not a regression.
4. **Code in the proxy grows.** Adds ~300–500 LOC across the four MQTT files. Code we have to maintain (and version-bump on changes). Bridge has been stable for the PDU, so the precedent's good.
5. **No native push from the matrix.** Even MQTT, if someone presses the front panel button, we still discover it through our 10 s proxy-side poll. MQTT doesn't make this device push-capable on its own.

## Recommended sequencing (if user says yes)

### Phase 1 — proxy ships MQTT, REST stays (v0.2.0 of the chart) · local-only

> **🚫 Do NOT push to any remote during this phase.**
>
> - `hdmi-matrix-proxy` is a **public GitHub repo**. Do not `git push` or `git push --tags`. No release will be created; no chart will be published to gh-pages.
> - `homelab-gitops` (private repo) edits are also local-only. Do not `git push`. Fleet will not roll the new chart version because the bundle won't see the update without a remote push.
> - All commits stay on the local `main` branches until the user explicitly authorizes pushing.

0. **Persist this plan as a markdown file in the proxy repo first** —
   copy this plan to `hdmi-matrix-proxy/docs/MQTT_MIGRATION_PLAN.md`
   so it survives beyond the plan file's session-scoped existence
   and can be referenced during and after execution.
1. Add `aiomqtt==2.0.1` to `requirements.txt`.
2. Add `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`, `MQTT_TOPIC_PREFIX`, `HA_DEVICE_NAME`, `HA_DEVICE_ID` to `app/config.py`.
3. Create `app/mqtt_client.py`, `app/discovery.py`, `app/poller.py`, `app/controller.py` — copy structure from cyberpower-pdu-mqtt-bridge. The controller subscribes to:
   - `matrix/routing/output/{1..8}/set` — per-output route change (called from each `select` entity's command topic).
   - `matrix/routing/preset/set` — atomic bulk routing, accepts JSON `{"output": "input"}` map and calls the existing `MatrixClient.set_preset()` for a single hardware operation.
4. Wire poller + controller as background tasks in `main.py`'s lifespan, alongside the existing matrix client.
5. Discovery payloads pin `object_id` so HA entity_ids match today's names. E.g. `select.matrix_output_3_source`, `sensor.matrix_output_3_current_source`. **This is the key migration-safety move.**
6. Bump chart `appVersion` to `0.2.0`, release.
7. Update `homelab-gitops/bundles/05-hdmi-matrix-proxy/helm/values.yaml` to set `mqtt.host: mqtt.mqtt.svc.cluster.local`, leave broker creds blank (anonymous in our cluster).
8. Commit locally in both repos (no push, no tag). User reviews diffs before any push to GitHub.

### Reminder — what happens if/when you DO push later

When the user later authorizes pushing:
- `git push origin main` + `git push origin v0.2.0` in `hdmi-matrix-proxy` → GitHub Actions publishes the new Helm chart to gh-pages.
- `git push origin main` in `homelab-gitops` → Fleet sees the bundle update and rolls the proxy pod with MQTT enabled.
Until then, the cluster is unchanged.

### Phase 2 — HA side cleanup (separate commit)

1. Verify the new MQTT-discovered entities are present and reading the same state as today's REST sensors. Run side-by-side for ~24 h.
2. Remove the 5 REST sensors from `configuration.yaml`.
3. Remove the 10 `rest_command` entries (the proxy still has the REST endpoints, but HA doesn't need to call them — MQTT command topics do the job).
4. Remove the 8 `input_select` entries (replaced by MQTT-discovered `select` entities).
5. Remove the 8 template sensors (replaced by MQTT-discovered `sensor` entities).
6. Hard-refresh dashboards; verify they still render. Update any that referenced removed entity_ids that we couldn't pin.
7. Run `sync-ha-config.sh` + commit.

### Phase 3 — proxy cleanup (optional, much later)

1. Mark the REST routing/preset endpoints deprecated.
2. After ~3 months of clean MQTT operation, drop them in v0.3.0.

## Decisions locked in

- **Names go on MQTT, not REST.** Input + output name lists become
  retained discovery attributes — embedded in each `select` entity's
  `options[]` array via the `homeassistant/select/.../config`
  payload. Re-published by the proxy whenever names change (on
  startup, and any time the proxy's poller observes a name delta
  from the matrix). Today's `sensor.hdmi_matrix_inputs` /
  `sensor.hdmi_matrix_outputs` REST sensors stop being needed —
  removed in Phase 2. (Conditional on dashboards still rendering
  correctly with the new MQTT-discovered selects — verified
  side-by-side in step 5 of Phase 1.)

## Out of scope / decisions deferred

- **Adding write/state-change webhooks from the matrix itself.** Not supported by the hardware.

## Capability coverage — does MQTT-only do everything HA does today?

Almost. Side-by-side:

| Today (REST) | MQTT-only equivalent | Match? |
|---|---|---|
| Read routing state | `select` entity, retained state topic per output | ✅ |
| Read input/output names | Embedded in `select.options[]` via discovery, re-publish on rename | ✅ |
| Read health / status | MQTT `binary_sensor` + MQTT availability (LWT detects pod death) | ✅ |
| Per-output route change | `select.select_option` → MQTT command topic | ✅ identical UX |
| Per-output `rest_command` (8×) | Implicit in each `select`'s command topic | ✅ |
| **Bulk preset routing** | Dedicated `matrix/routing/preset/set` topic in proxy (option b); HA scripts call via `mqtt.publish` | ✅ atomic, single hardware operation |

**Recommendation: keep the proxy's REST endpoints indefinitely** as
belt-and-suspenders. MQTT becomes the primary path used by HA's
dashboards + automations; REST stays for power-user scripts,
debugging, and the bulk-preset atomicity case. Costs nothing in
the proxy to leave both code paths active; eliminates the one
ergonomic gap.

## Files that would change (Phase 1 only)

| Repo | File | Action |
|---|---|---|
| `hdmi-matrix-proxy/app/` | `config.py`, `main.py` | Add MQTT settings; wire lifespan tasks |
| `hdmi-matrix-proxy/app/` | `mqtt_client.py`, `discovery.py`, `poller.py`, `controller.py` | New files (copy structure from PDU bridge) |
| `hdmi-matrix-proxy/` | `requirements.txt`, `VERSION`, `chart/Chart.yaml`, `chart/values.yaml` | Bump versions, add MQTT config + secret support |
| `homelab-gitops/bundles/05-hdmi-matrix-proxy/` | `fleet.yaml`, `helm/values.yaml` | Bump chart version, wire MQTT host |
| `docs/content/architecture/apps/05-hdmi-matrix.md` | doc | Update for MQTT integration |
| `docs/doc-sync.yaml` | (no change — bundle path already mapped) | — |

## Verification (Phase 1 only)

1. `kubectl -n home-assistant logs deploy/hdmi-matrix-proxy` after roll — expect MQTT client connected + discovery payloads published.
2. `kubectl exec -n mqtt mqtt-0 -- mosquitto_sub -h localhost -t 'matrix/#' -v` — expect routing/state topics ticking every ~10 s.
3. HA UI Settings → Devices & Services → MQTT → "HDMI Matrix" device card should appear with all entities.
4. Side-by-side: HA's existing `sensor.matrix_output_1_current_source` (REST-derived) vs the new MQTT-discovered version. Same value? Good.

## Counter-argument: just don't

If you're not actively extending the matrix integration, "do nothing"
is also valid. The current 315-line setup is verbose but stable.
Migration cost is mostly paid up-front; if no new outputs / inputs
are coming and existing dashboards work, the savings are theoretical.
The case to migrate gets stronger if:
- You're about to rename or add inputs/outputs (the 4-place edit pain hits you).
- You're planning more MQTT producers anyway (consistency dividend grows).
- You're cleaning up `configuration.yaml` for any other reason.

The case to *defer* gets stronger if:
- The matrix is stable and not changing.
- You don't want to risk dashboard breakage right now.
- Other projects compete for your attention.
