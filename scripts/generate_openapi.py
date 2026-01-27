#!/usr/bin/env python3
"""Generate OpenAPI specification file."""

import json
from pathlib import Path

from app.main import app

# Get OpenAPI schema
openapi_schema = app.openapi()

# Write to docs directory
docs_dir = Path(__file__).parent.parent / "docs"
docs_dir.mkdir(exist_ok=True)

output_file = docs_dir / "openapi.json"
with open(output_file, "w") as f:
    json.dump(openapi_schema, f, indent=2)

print(f"OpenAPI specification written to {output_file}")
