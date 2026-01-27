# Home Assistant Integration

This guide shows how to integrate the HDMI Matrix Proxy with Home Assistant.

## Prerequisites

- HDMI Matrix Proxy running and accessible from Home Assistant
- Home Assistant with REST integration enabled

## Configuration

### 1. Basic REST Commands

Add these to your `configuration.yaml`:

```yaml
rest_command:
  # Individual output control (example for output 1)
  matrix_output_1:
    url: "http://hdmi-matrix-proxy:8080/api/routing/output/1"
    method: POST
    content_type: "application/json"
    payload: '{"input": {{ input }}}'

  # Repeat for each output (2-8)
  matrix_output_2:
    url: "http://hdmi-matrix-proxy:8080/api/routing/output/2"
    method: POST
    content_type: "application/json"
    payload: '{"input": {{ input }}}'

  # ... outputs 3-8 ...

  # Preset routing (set all outputs at once)
  matrix_preset:
    url: "http://hdmi-matrix-proxy:8080/api/routing/preset"
    method: POST
    content_type: "application/json"
    payload: '{"mappings": {{ mappings }}}'
```

### 2. REST Sensors

Monitor matrix status and routing with custom names:

```yaml
rest:
  - resource: "http://hdmi-matrix-proxy:8080/api/status"
    scan_interval: 30
    sensor:
      - name: "HDMI Matrix Status"
        value_template: "{{ value_json.connection }}"
        json_attributes:
          - url
          - last_command

  - resource: "http://hdmi-matrix-proxy:8080/healthz/ready"
    scan_interval: 30
    sensor:
      - name: "HDMI Matrix Health"
        value_template: "{{ value_json.status }}"
        json_attributes:
          - matrix_connected
          - uptime_seconds

  # Routing sensor with custom names
  - resource: "http://hdmi-matrix-proxy:8080/api/routing"
    scan_interval: 10
    sensor:
      - name: "HDMI Matrix Routing"
        value_template: "{{ value_json.outputs | length }}"
        json_attributes:
          - outputs
          - input_names
          - output_names
```

**Custom Names**: The `/api/routing` endpoint now includes `input_names` and `output_names` dictionaries with the custom names you've configured in the matrix web UI. This makes it easy to display meaningful names in Home Assistant instead of generic "HDMI 1", "Output 1", etc.

### 3. Using Custom Names in Templates

The API now returns custom names you've set in the matrix web UI. Here's how to use them:

```yaml
# Template sensor to show current input for an output using custom names
template:
  - sensor:
      - name: "Theater TV Current Source"
        state: >
          {% set routing = state_attr('sensor.hdmi_matrix_routing', 'outputs') %}
          {% set output = routing | selectattr('output', 'eq', 1) | first %}
          {{ output.input_name if output.input_name else 'Unknown' }}
        attributes:
          output_name: >
            {% set routing = state_attr('sensor.hdmi_matrix_routing', 'outputs') %}
            {% set output = routing | selectattr('output', 'eq', 1) | first %}
            {{ output.output_name }}
          
      - name: "All Input Names"
        state: "{{ state_attr('sensor.hdmi_matrix_routing', 'input_names') | length }}"
        attributes:
          names: "{{ state_attr('sensor.hdmi_matrix_routing', 'input_names') }}"
          
      - name: "All Output Names"
        state: "{{ state_attr('sensor.hdmi_matrix_routing', 'output_names') | length }}"
        attributes:
          names: "{{ state_attr('sensor.hdmi_matrix_routing', 'output_names') }}"
```

### 4. Input Select Helpers with Custom Names

Create input selects for each output. You can manually configure these with your custom names, or use the generic format and rely on template sensors to display the actual custom names:

```yaml
input_select:
  hdmi_matrix_output_1:
    name: "Theater TV Input"  # Use your custom output name
    options:
      - "1"  # We'll use numbers and display names via templates
      - "2"
      - "3"
      - "4"
      - "5"
      - "6"
      - "7"
      - "8"
    initial: "1"
    icon: mdi:video-input-hdmi

  # Repeat for outputs 2-8
  hdmi_matrix_output_2:
    name: "Left Pool Table TV Input"  # Use your custom output name
    options:
      - "1"
      - "2"
      - "3"
      - "4"
      - "5"
      - "6"
      - "7"
      - "8"
    initial: "1"
    icon: mdi:video-input-hdmi
  
  # ... outputs 3-8 ...
```

### 5. Automations

Create automations to sync input selects with matrix commands:

```yaml
automation:
  # Output 1 automation
  - id: hdmi_matrix_output_1_changed
    alias: "HDMI Matrix - Output 1 Changed"
    trigger:
      platform: state
      entity_id: input_select.hdmi_matrix_output_1
    action:
      service: rest_command.matrix_output_1
      data:
        input: >
          {{ trigger.to_state.state.split(' ')[1] | int }}

  # Repeat for outputs 2-8
  - id: hdmi_matrix_output_2_changed
    alias: "HDMI Matrix - Output 2 Changed"
    trigger:
      platform: state
      entity_id: input_select.hdmi_matrix_output_2
    action:
      service: rest_command.matrix_output_2
      data:
        input: >
          {{ trigger.to_state.state.split(' ')[1] | int }}
  
  # ... outputs 3-8 ...
```

### 6. Scripts

Create reusable scripts for common routing scenarios:

```yaml
script:
  # All inputs to matching outputs (1→1, 2→2, etc.)
  matrix_default_routing:
    alias: "HDMI Matrix - Default Routing"
    sequence:
      - service: rest_command.matrix_preset
        data:
          mappings: '{"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8}'

  # All outputs to input 1
  matrix_all_to_input_1:
    alias: "HDMI Matrix - All to Input 1"
    sequence:
      - service: rest_command.matrix_preset
        data:
          mappings: '{"1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1, "8": 1}'

  # Custom preset example
  matrix_movie_mode:
    alias: "HDMI Matrix - Movie Mode"
    sequence:
      - service: rest_command.matrix_preset
        data:
          mappings: '{"1": 3, "2": 3, "3": 3, "4": 4}'  # TVs 1-3 to Blu-ray, TV 4 to AppleTV
```

### 7. Lovelace Dashboard with Custom Names

Here's a dashboard that shows the custom names:

```yaml
type: vertical-stack
cards:
  # Status card
  - type: entities
    title: HDMI Matrix Status
    entities:
      - entity: sensor.hdmi_matrix_status
        name: Connection
      - entity: sensor.hdmi_matrix_health
        name: Health
      - entity: sensor.theater_tv_current_source
        name: Theater TV Source
        icon: mdi:television

  # Control card with template sensors showing custom names
  - type: entities
    title: HDMI Matrix Routing
    entities:
      - entity: input_select.hdmi_matrix_output_1
        name: >
          {% set names = state_attr('sensor.hdmi_matrix_routing', 'output_names') %}
          {{ names['1'] if names else 'Output 1' }}
      - entity: input_select.hdmi_matrix_output_2
        name: >
          {% set names = state_attr('sensor.hdmi_matrix_routing', 'output_names') %}
          {{ names['2'] if names else 'Output 2' }}
      - entity: input_select.hdmi_matrix_output_3
        name: >
          {% set names = state_attr('sensor.hdmi_matrix_routing', 'output_names') %}
          {{ names['3'] if names else 'Output 3' }}
      - entity: input_select.hdmi_matrix_output_4
        name: >
          {% set names = state_attr('sensor.hdmi_matrix_routing', 'output_names') %}
          {{ names['4'] if names else 'Output 4' }}
      # Continue for outputs 5-8...

  # Preset scripts card
  - type: entities
    title: Quick Presets
    entities:
      - entity: script.matrix_default_routing
        name: "Default Routing"
        icon: mdi:refresh
      - entity: script.matrix_all_to_input_1
        name: "All to Input 1"
        icon: mdi:numeric-1-box
      - entity: script.matrix_movie_mode
        name: "Movie Mode"
        icon: mdi:movie
```

### 8. Original Lovelace Dashboard

Create a dashboard card to control the matrix:

```yaml
type: vertical-stack
cards:
  # Status card
  - type: entities
    title: HDMI Matrix Status
    entities:
      - entity: sensor.hdmi_matrix_status
        name: Connection
      - entity: sensor.hdmi_matrix_health
        name: Health

  # Control card
  - type: entities
    title: HDMI Matrix Routing
    entities:
      - entity: input_select.hdmi_matrix_output_1
        name: "TV 1"
      - entity: input_select.hdmi_matrix_output_2
        name: "TV 2"
      - entity: input_select.hdmi_matrix_output_3
        name: "TV 3"
      - entity: input_select.hdmi_matrix_output_4
        name: "TV 4"
      - entity: input_select.hdmi_matrix_output_5
        name: "TV 5"
      - entity: input_select.hdmi_matrix_output_6
        name: "TV 6"
      - entity: input_select.hdmi_matrix_output_7
        name: "TV 7"
      - entity: input_select.hdmi_matrix_output_8
        name: "TV 8"

  # Preset scripts card
  - type: entities
    title: Quick Presets
    entities:
      - entity: script.matrix_default_routing
        name: "Default Routing"
        icon: mdi:refresh
      - entity: script.matrix_all_to_input_1
        name: "All to Input 1"
        icon: mdi:numeric-1-box
      - entity: script.matrix_movie_mode
        name: "Movie Mode"
        icon: mdi:movie
```

### 7. Advanced: Grid Selector

For a more visual matrix selector, use a custom button card:

```yaml
type: grid
columns: 8
cards:
  # Row for each output
  - type: custom:button-card
    name: "O1→I1"
    tap_action:
      action: call-service
      service: rest_command.matrix_output_1
      service_data:
        input: 1
  
  # Continue for all 64 combinations (8 outputs × 8 inputs)
  # This creates an 8×8 grid of buttons
```

## Usage Examples

### Set Single Output

```yaml
# In an automation or script
service: rest_command.matrix_output_1
data:
  input: 3  # Route input 3 to output 1
```

### Set Multiple Outputs

```yaml
service: rest_command.matrix_preset
data:
  mappings: '{"1": 2, "2": 3, "3": 4}'  # Set multiple at once
```

### Check Status

```yaml
# In a template sensor
{{ states('sensor.hdmi_matrix_status') }}
{{ state_attr('sensor.hdmi_matrix_health', 'matrix_connected') }}
```

## Troubleshooting

### Connection Issues

1. Check that the proxy is accessible:
   ```bash
   curl http://hdmi-matrix-proxy:8080/healthz/live
   ```

2. Verify matrix URL in proxy configuration:
   ```bash
   curl http://hdmi-matrix-proxy:8080/api/status
   ```

### Command Not Working

1. Test directly with curl:
   ```bash
   curl -X POST http://hdmi-matrix-proxy:8080/api/routing/output/1 \
     -H "Content-Type: application/json" \
     -d '{"input": 1}'
   ```

2. Check Home Assistant logs for REST command errors

3. Verify the REST command payload format

## Notes

- **State Tracking**: The matrix may not report its current state. Consider tracking state in Home Assistant using input selects.
- **Initialization**: On Home Assistant restart, input selects reset to their initial values. You may want to add an automation to set a known state on startup.
- **Custom Names**: The proxy automatically retrieves custom input and output names from the matrix web UI. These names are included in the `/api/routing` endpoint response and can be used in Home Assistant templates for a more user-friendly interface.

## Custom Names Feature

The proxy now supports retrieving the custom names you've configured in the matrix web UI (vsw.html page):

### How It Works

1. **Matrix Configuration**: Set custom names in the matrix web UI by checking "Modify Name" and entering your desired names
2. **Automatic Retrieval**: The proxy automatically fetches these names when you query `/api/routing` or `/api/routing/output/{id}`
3. **API Response**: Names are included in the JSON response:
   ```json
   {
     "outputs": [
       {
         "output": 1,
         "output_name": "Theater TV",
         "input": 3,
         "input_name": "G Streamer 3"
       }
     ],
     "input_names": {
       "1": "G Streamer 1",
       "2": "G Streamer 2",
       ...
     },
     "output_names": {
       "1": "Theater TV",
       "2": "Left Pool Table TV",
       ...
     }
   }
   ```

### Benefits

- **User-Friendly**: See "Theater TV" instead of "Output 1" and "Playstation 5" instead of "HDMI 6"
- **Automatic Sync**: Names automatically update when you change them in the matrix web UI
- **Template Support**: Use names in Home Assistant templates, cards, and automations
- **Fallback**: If names aren't set or can't be retrieved, falls back to generic names (HDMI 1, Output 1, etc.)

## Example Complete Configuration

See **[ha-config/](ha-config/)** directory for a complete working example with:
- `configuration.yaml` - REST sensors, REST commands, input helpers, template sensors
- `automations.yaml` - All 8 output automations with two-way sync
- `scripts.yaml` - Preset routing scripts (gaming, movie, sports, etc.)
- `dashboard.yaml` - Lovelace dashboard card with custom names
- `README.md` - Installation and customization guide

These files are ready to use and include the custom names feature!

## Further Customization

You can extend this integration with:

- **Scenes**: Save and restore complete routing configurations
- **Templates**: Create template sensors for input/output labels
- **Notifications**: Alert when routing changes
- **Conditions**: Conditional routing based on time, presence, etc.
