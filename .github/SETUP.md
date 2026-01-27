# HDMI Matrix Proxy - Setup Guide

This document provides instructions for setting up and deploying the HDMI Matrix Proxy.

## Prerequisites

- Python 3.12+
- Docker (for containerized deployment)
- Kubernetes cluster with Helm (for production deployment)
- MT-VIKI MT-H8M88 8x8 HDMI Matrix with web interface

## Local Development

### 1. Install Dependencies

```bash
make install
```

This creates a virtual environment and installs all required dependencies.

### 2. Configure Environment

Create a `.env` file or export environment variables:

```bash
export MATRIX_URL="http://your-matrix-ip"
export MATRIX_VERIFY_SSL="false"
export LOG_LEVEL="INFO"
```

### 3. Run Development Server

```bash
make dev
```

The API will be available at `http://localhost:8080/docs`

### 4. Run Tests

```bash
make test
```

### 5. Lint Code

```bash
make lint
```

## Docker Deployment

### Build Image

```bash
make build
```

### Run Container

```bash
docker run -d \
  --name hdmi-matrix-proxy \
  -p 8080:8080 \
  -e MATRIX_URL=http://your-matrix-ip \
  ghcr.io/willysamz/hdmi-matrix-proxy:latest
```

## Kubernetes Deployment

### Using Helm

1. Update `chart/values.yaml` with your matrix URL:

```yaml
config:
  matrixUrl: "http://your-matrix-ip-or-hostname"
```

2. Install the chart:

```bash
helm install matrix ./chart
```

3. Verify deployment:

```bash
kubectl get pods -l app.kubernetes.io/name=hdmi-matrix-proxy
kubectl logs -l app.kubernetes.io/name=hdmi-matrix-proxy
```

### Custom Values

Create a `custom-values.yaml`:

```yaml
config:
  matrixUrl: "http://192.168.1.100"
  matrixTimeout: "10.0"

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 128Mi

logging:
  level: DEBUG
```

Install with custom values:

```bash
helm install matrix ./chart -f custom-values.yaml
```

## Testing the API

### Health Check

```bash
curl http://localhost:8080/healthz/live
curl http://localhost:8080/healthz/ready
```

### Get Routing State

```bash
curl http://localhost:8080/api/routing
```

### Set Routing

```bash
# Route input 3 to output 1
curl -X POST http://localhost:8080/api/routing/output/1 \
  -H "Content-Type: application/json" \
  -d '{"input": 3}'
```

### Set Multiple Routes

```bash
curl -X POST http://localhost:8080/api/routing/preset \
  -H "Content-Type: application/json" \
  -d '{"mappings": {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8}}'
```

## Configuration Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MATRIX_URL` | Matrix web interface URL | `http://matrix.home.willysamz.com` |
| `MATRIX_TIMEOUT` | HTTP request timeout (seconds) | `5.0` |
| `MATRIX_VERIFY_SSL` | Verify SSL certificates | `false` |
| `MATRIX_HEALTH_INTERVAL` | Health check interval (seconds) | `30` |
| `SERVER_HOST` | Server bind address | `0.0.0.0` |
| `SERVER_PORT` | Server port | `8080` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `LOG_JSON` | Output logs as JSON | `true` |

### Matrix Commands

The MT-VIKI MT-H8M88 uses these command formats:

- **Route input to output**: `SW+<input>+<output>`
  - Example: `SW+1+1` routes input 1 to output 1
  - Inputs: 1-8
  - Outputs: 1-8

The proxy sends commands to: `POST http://matrix-url/form-system-cmd.cgi`

## Troubleshooting

### Connection Issues

1. **Cannot reach matrix**:
   - Verify matrix URL is correct
   - Check network connectivity: `curl http://matrix-ip`
   - Check firewall rules

2. **Commands not working**:
   - Verify matrix web UI is accessible
   - Test commands directly: `curl -X POST 'http://matrix-ip/form-system-cmd.cgi' -d 'cmd=SW+1+1'`
   - Check proxy logs: `kubectl logs -l app.kubernetes.io/name=hdmi-matrix-proxy`

3. **Health check failing**:
   - Check matrix URL in configuration
   - Verify SSL settings (try `MATRIX_VERIFY_SSL=false` for self-signed certs)
   - Increase timeout: `MATRIX_TIMEOUT=10.0`

### Development Issues

1. **Import errors**:
   - Ensure virtual environment is activated: `source .venv/bin/activate`
   - Reinstall dependencies: `make install`

2. **Linting errors**:
   - Auto-fix: `make lint-fix`
   - Check specific issues: `make lint`

3. **Test failures**:
   - Run with verbose output: `.venv/bin/pytest tests/ -v`
   - Run specific test: `.venv/bin/pytest tests/test_api.py::test_name -v`

## CI/CD

The project includes GitHub Actions workflows:

- **CI** (`.github/workflows/ci.yml`): Runs on every push/PR
  - Linting (ruff, mypy)
  - Testing (pytest)
  - Helm chart validation

- **Build Main** (`.github/workflows/build-main.yml`): Runs on main branch
  - Builds and pushes Docker image to GHCR
  - Multi-arch support (amd64, arm64)

- **Release** (`.github/workflows/release.yml`): Runs on version tags
  - Validates version consistency
  - Builds and tags Docker images
  - Publishes Helm chart
  - Creates GitHub release

### Creating a Release

```bash
# Bump version (patch, minor, or major)
make bump-patch

# The above command updates VERSION, pyproject.toml, and app/__init__.py
# Commit and push
git push origin main --tags
```

## Security Considerations

1. **Network Security**:
   - Matrix communication is over HTTP (not HTTPS by default)
   - Consider using network policies in Kubernetes
   - Restrict access to management network

2. **Container Security**:
   - Runs as non-root user (UID 1000)
   - No privileged access required
   - Minimal container image

3. **API Security**:
   - No authentication built-in (add reverse proxy with auth if needed)
   - Consider adding API key or basic auth for production

## Next Steps

1. **Home Assistant Integration**: See [docs/home-assistant.md](../docs/home-assistant.md)
2. **Monitoring**: Add Prometheus metrics (future enhancement)
3. **State Tracking**: Implement local state tracking for routing (future enhancement)
4. **Custom Commands**: Extend API for additional matrix features (future enhancement)

## Support

For issues or questions:
- Open an issue on GitHub
- Check existing issues for solutions
- Review the [README.md](../README.md) for more information
