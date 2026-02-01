# Home Assistant Configuration Files

Ready-to-use configuration files for integrating the HDMI Matrix Proxy with Home Assistant.

## Zero Configuration Required

**All names come from the API automatically!** Just:

1. Configure your input/output names in the **matrix web UI**
2. Copy these files to Home Assistant
3. Restart - names sync automatically

No need to edit YAML files when you rename devices.

## How It Works

1. **On startup**, an automation fetches input names from `/api/inputs`
2. **Dropdown options** are populated dynamically via `input_select.set_options`
3. **Output names** display via template sensors that read from `/api/routing`
4. **Dashboard cards** reference the template sensors for dynamic names

## Files

| File | Description |
|------|-------------|
| `configuration.yaml` | REST sensors, REST commands, input_selects (auto-populated), template sensors |
| `automations.yaml` | Startup sync, routing sync, output change handlers |
| `scripts.yaml` | Preset routing scripts |
| `dashboard.yaml` | Bubble Card dashboard (requires HACS) |

## Prerequisites

### Install Bubble Card (for dashboard)

1. Install [HACS](https://hacs.xyz/) if you haven't already
2. Go to HACS → Frontend → Explore & Download
3. Search for "Bubble Card" and install
4. Restart Home Assistant

## Installation

### Option 1: Include Files Directly

If you use packages or split configuration:

```yaml
# In configuration.yaml
homeassistant:
  packages:
    hdmi_matrix: !include hdmi-matrix/configuration.yaml

automation: !include_dir_merge_list automations/
script: !include_dir_merge_named scripts/
```

### Option 2: Merge Into Existing Config

Copy the contents of each file into your existing configuration files.

### Add Dashboard

1. Go to Settings → Dashboards
2. Create a new dashboard or edit existing
3. Switch to YAML mode (three dots → Raw configuration editor)
4. Paste the desired layout from `dashboard.yaml`

## Configuration

### Service URL

Update the proxy URL in `configuration.yaml` if needed:

```yaml
rest:
  - resource: "http://YOUR-PROXY-ADDRESS:8080/api/inputs"
```

Replace `hdmi-matrix-proxy` with your actual hostname/IP.

### Customize Presets

Edit `scripts.yaml` to customize the preset buttons. Use numbers or names:

```yaml
# Using numbers
mappings: '{"mappings": {"1": 3, "2": 4}}'

# Using names (must match matrix web UI exactly)
mappings: '{"mappings": {"Living Room TV": "PlayStation 5", "Bedroom TV": "Apple TV"}}'
```

## API Reference

### Get Names

```bash
# Input names (for dropdown options)
GET /api/inputs
# Returns: {"inputs": [...], "names": ["Apple TV", "Roku", ...]}

# Output names
GET /api/outputs  
# Returns: {"outputs": [...], "names": ["Living Room TV", ...]}
```

### Set Routing

```bash
# By number
POST /api/routing/output/1
{"input": 3}

# By name (URL-encode spaces)
POST /api/routing/output/Living%20Room%20TV
{"input": "PlayStation 5"}
```

### Preset Routing

```bash
POST /api/routing/preset
{"mappings": {"Living Room TV": "Apple TV", "2": 3, "Bedroom TV": "Roku"}}
```

## Troubleshooting

### Dropdowns show "Loading..."

The startup automation hasn't run yet or the API is unreachable.

1. Check that `sensor.hdmi_matrix_inputs` has data (Developer Tools → States)
2. Manually trigger: Developer Tools → Services → `automation.trigger` → `matrix_sync_input_names_on_startup`

### Names not updating

1. Verify names in matrix web UI
2. Check `/api/inputs` returns correct names
3. Restart Home Assistant to re-trigger startup automation

### Dashboard shows "Unknown" for output names

The routing sensor hasn't loaded yet. Wait for it to refresh or manually update:

Developer Tools → Services → `homeassistant.update_entity` → `sensor.hdmi_matrix_routing`

## Architecture

```
Matrix Web UI (vsw.html)
    │
    ▼ Configure names
HDMI Matrix Hardware
    │
    ▼ Names stored
HDMI Matrix Proxy API
    │
    ├─► /api/inputs  ──► sensor.hdmi_matrix_inputs ──► input_select options
    ├─► /api/outputs ──► sensor.hdmi_matrix_outputs
    └─► /api/routing ──► sensor.hdmi_matrix_routing ──► template sensors ──► dashboard
```
