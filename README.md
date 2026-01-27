# HDMI Matrix Proxy

REST API proxy for controlling MT-VIKI MT-H8M88 8x8 HDMI matrix via HTTP.

## Features

- HTTP communication with MT-H8M88 HDMI matrix
- RESTful API with OpenAPI documentation
- Kubernetes-ready with Helm chart
- Home Assistant integration support
- Automatic health monitoring
- Health endpoints for liveness/readiness probes

## Quick Start

### Using Docker

```bash
docker run -d \
  --name hdmi-matrix-proxy \
  -p 8080:8080 \
  -e MATRIX_URL=http://your-matrix-ip \
  ghcr.io/willysamz/hdmi-matrix-proxy:latest
```

### Using Helm

```bash
# Install directly from the Git repository
helm install matrix ./chart \
  --set config.matrixUrl=http://your-matrix-ip
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `MATRIX_URL` | Matrix web interface URL | `http://matrix.home.willysamz.com` |
| `MATRIX_TIMEOUT` | Request timeout (seconds) | `5.0` |
| `MATRIX_VERIFY_SSL` | Verify SSL certificates | `false` |
| `MATRIX_HEALTH_INTERVAL` | Health check interval (seconds) | `30` |
| `SERVER_PORT` | HTTP server port | `8080` |
| `LOG_LEVEL` | Log level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `LOG_JSON` | Output logs as JSON | `true` |

## API Endpoints

Once running, visit `http://localhost:8080/docs` for interactive API documentation.

### Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/healthz/live` | GET | Liveness probe |
| `/healthz/ready` | GET | Readiness probe |
| `/api/status` | GET | Matrix connection status |
| `/api/routing` | GET | Get all routing state (8 outputs) |
| `/api/routing/output/{id}` | GET | Get routing for specific output |
| `/api/routing/output/{id}` | POST | Set input for specific output |
| `/api/routing/preset` | POST | Set multiple routings at once |

### API Examples

```bash
# Get all routing state
curl http://localhost:8080/api/routing

# Route input 3 to output 1
curl -X POST http://localhost:8080/api/routing/output/1 \
  -H "Content-Type: application/json" \
  -d '{"input": 3}'

# Set multiple routings (preset)
curl -X POST http://localhost:8080/api/routing/preset \
  -H "Content-Type: application/json" \
  -d '{"mappings": {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8}}'
```

## Home Assistant Integration

See [docs/home-assistant.md](docs/home-assistant.md) for detailed integration instructions.

Quick example:

```yaml
rest_command:
  matrix_route_output_1:
    url: http://hdmi-matrix-proxy:8080/api/routing/output/1
    method: POST
    content_type: application/json
    payload: '{"input": {{ input }}}'
```

## Development

```bash
# Install dependencies
make install

# Run development server
make dev

# Run tests
make test

# Lint code
make lint
```

## Matrix Commands

The MT-VIKI MT-H8M88 uses the following command format:

- **Route input to output**: `SW+<input>+<output>`
  - Example: `SW+1+1` routes input 1 to output 1
  - Input range: 1-8
  - Output range: 1-8

## Documentation

- [Home Assistant Integration](docs/home-assistant.md)
- [OpenAPI Specification](docs/openapi.json) (generate with `make openapi`)

## Architecture

This proxy acts as a REST API wrapper around the matrix's web interface, converting HTTP REST calls into matrix CGI commands.

```
┌─────────────────┐
│  Home Assistant │
│   or Client     │
└────────┬────────┘
         │ REST API
         ▼
┌─────────────────┐
│  Matrix Proxy   │
│   (FastAPI)     │
└────────┬────────┘
         │ HTTP POST
         ▼
┌─────────────────┐
│   MT-H8M88      │
│  HDMI Matrix    │
│   (Web CGI)     │
└─────────────────┘
```

## License

MIT
