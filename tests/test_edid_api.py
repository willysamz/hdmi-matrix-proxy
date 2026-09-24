"""REST tests for the EDID endpoints.

The house's matrix scenes are REST — `script.ps5_gaming_preset` runs
`rest_command.matrix_preset`, and every matrix script is a
`rest_command.matrix_*` against this proxy — so an MQTT-only EDID surface
would leave the scenes with no way to set one.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import dependencies
from app.edid import EdidCatalogue
from app.main import app
from app.matrix_client import MatrixClient
from app.models import ConnectionState

SYS8 = "SYS 8 · UHD4K60"


async def _fake_read_edid(source, index):
    if source == "sys" and 1 <= index <= 10:
        return {"name": "whatever", "hex": f"sys{index}"}
    if source == "user" and 1 <= index <= 5:
        return {"name": "whatever", "hex": f"user{index}"}
    return None


@pytest.fixture
def mock_matrix_client():
    client = MagicMock(spec=MatrixClient)
    client.connection_state = ConnectionState.CONNECTED
    client.last_command_time = None
    client.last_response = None
    client.get_input_names = AsyncMock(return_value={i: f"In {i}" for i in range(1, 9)})
    client.get_output_names = AsyncMock(return_value={i: f"Out {i}" for i in range(1, 9)})
    client.get_routing_state = AsyncMock(return_value={})
    client.read_edid = AsyncMock(side_effect=_fake_read_edid)
    client.set_input_edid = AsyncMock(return_value=True)
    client.start = AsyncMock()
    client.stop = AsyncMock()
    return client


@pytest.fixture
def api(mock_matrix_client):
    # The catalogue is a process-wide singleton; give each test a fresh one.
    dependencies._edid_catalogue = EdidCatalogue()
    with patch("app.main.MatrixClient", return_value=mock_matrix_client):
        with TestClient(app) as client:
            yield client


def test_get_catalogue_builds_on_demand_when_nothing_has_built_it(api):
    """With MQTT disabled nothing builds it, so the REST path probes — on
    request, never on the boot path."""
    response = api.get("/api/edid")
    assert response.status_code == 200
    data = response.json()
    assert data["loaded"] is True
    assert SYS8 in data["labels"]
    # Code-owned labels, not the device's `edid_name`.
    assert not any("whatever" in label for label in data["labels"])
    # No "copy from output" options in v1.
    assert all(o["source"] in ("sys", "user") for o in data["options"])


def test_set_edid_by_source_and_index(api, mock_matrix_client):
    response = api.post("/api/edid", json={"source": "sys", "index": 8, "input": 6})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["input"] == 6
    assert data["rehandshake"] is True
    mock_matrix_client.set_input_edid.assert_awaited_once_with("sys", 8, 6, rehandshake=True)


def test_set_edid_can_skip_the_rehandshake(api, mock_matrix_client):
    api.post("/api/edid", json={"source": "sys", "index": 8, "input": 6, "rehandshake": False})
    mock_matrix_client.set_input_edid.assert_awaited_once_with("sys", 8, 6, rehandshake=False)


def test_set_edid_reports_a_refusal_rather_than_claiming_success(api, mock_matrix_client):
    """The device answers plenty it then ignores; the body is the only
    confirmation there is."""
    mock_matrix_client.set_input_edid = AsyncMock(return_value=False)
    response = api.post("/api/edid", json={"source": "sys", "index": 8, "input": 6})
    assert response.status_code == 200
    assert response.json()["success"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"source": "sys", "index": 8, "input": 0},
        {"source": "sys", "index": 8, "input": None},
        {"source": "sys", "index": 8},
        {"source": "sys", "index": 8, "input": 9},
        {"source": "sys", "index": 0, "input": 6},
        {"source": "bogus", "index": 8, "input": 6},
    ],
)
def test_set_edid_rejects_bad_bodies(api, mock_matrix_client, body):
    """`input` is required and 1-8. There is no all-inputs form over REST: a
    misfired body must not retune every source in the house."""
    response = api.post("/api/edid", json=body)
    assert response.status_code == 422
    mock_matrix_client.set_input_edid.assert_not_awaited()


def test_set_edid_maps_an_out_of_range_index_to_400(api, mock_matrix_client):
    """`index` has no upper bound in the schema — the per-source ceiling
    lives in the client, and its ValueError becomes a 400."""
    mock_matrix_client.set_input_edid = AsyncMock(side_effect=ValueError("bad index"))
    response = api.post("/api/edid", json={"source": "sys", "index": 99, "input": 6})
    assert response.status_code == 400


def test_set_edid_maps_a_transport_failure_to_503(api, mock_matrix_client):
    mock_matrix_client.set_input_edid = AsyncMock(side_effect=RuntimeError("unreachable"))
    response = api.post("/api/edid", json={"source": "sys", "index": 8, "input": 6})
    assert response.status_code == 503
