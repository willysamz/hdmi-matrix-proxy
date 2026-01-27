# Home Assistant Configuration Files

Ready-to-use configuration files for integrating the HDMI Matrix Proxy with Home Assistant.

## Files

| File | Description |
|------|-------------|
| `configuration.yaml` | REST sensors, REST commands, input helpers, template sensors |
| `automations.yaml` | Two-way sync between input selects and matrix |
| `scripts.yaml` | Preset routing scripts |
| `dashboard.yaml` | Lovelace dashboard card with custom names |

## Features

- **Custom Names Support**: Automatically displays the custom input/output names you've configured in the matrix web UI
- **8x8 Matrix Control**: Full control of all 8 inputs and 8 outputs
- **Template Sensors**: Shows current routing with custom names
- **Preset Scripts**: Quick routing configurations for common scenarios

## Installation

### Option 1: Merge into existing files

Copy the contents of each file into your corresponding Home Assistant config files.

### Option 2: Use includes

Add these to your `configuration.yaml`:

```yaml
# If you use separate files for automations/scripts
automation: !include automations.yaml
script: !include scripts.yaml
```

Then copy the `rest:`, `rest_command:`, `input_select:`, and `template:` sections from `configuration.yaml` into your main config.

### Dashboard

1. Go to your Lovelace dashboard
2. Click Edit → Add Card → Manual
3. Paste the contents of `dashboard.yaml`

## Customization

Before using, you may need to update:

1. **Service URL**: Replace `http://hdmi-matrix-proxy:8080` with your actual proxy address
2. **Output Names**: The examples use generic names; your actual custom names will be fetched automatically
3. **Preset Scripts**: Customize the routing presets in `scripts.yaml` to match your needs

## After Installation

1. **Check Configuration**: Settings → System → Check Configuration
2. **Restart Home Assistant**
3. **Verify Sensor**: Check that `sensor.hdmi_matrix_routing` is populating with data
4. **View Custom Names**: The template sensors should show your custom input/output names
5. **Create Area** (optional): Create an "HDMI Matrix" area and assign all entities to it

## Custom Names

The proxy automatically retrieves custom names from your matrix web UI. These appear in:

- `sensor.hdmi_matrix_routing` attributes (`input_names` and `output_names`)
- Template sensors that display current source with custom names
- API responses for programmatic access

To set custom names:
1. Open your matrix web UI (vsw.html)
2. Check "Modify Name" checkbox
3. Enter custom names for each input/output
4. Uncheck "Modify Name" to save

The proxy will fetch these names automatically on every routing query.
