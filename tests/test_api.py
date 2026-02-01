"""API endpoint tests."""

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.matrix_client import MatrixClient
from app.models import ConnectionState


@pytest.fixture
def mock_matrix_client():
    """Create a mock matrix client."""
    client = MagicMock(spec=MatrixClient)
    client.connection_state = ConnectionState.CONNECTED
    client.last_command_time = None
    client.last_response = None
    client.set_routing = AsyncMock(return_value=True)
    client.get_routing_state = AsyncMock(return_value={})
    client.get_input_names = AsyncMock(return_value={
        1: "Input A", 2: "Input B", 3: "Input C", 4: "Input D",
        5: "Input E", 6: "Input F", 7: "Input G", 8: "Input H"
    })
    client.get_output_names = AsyncMock(return_value={
        1: "TV 1", 2: "TV 2", 3: "TV 3", 4: "TV 4",
        5: "TV 5", 6: "TV 6", 7: "TV 7", 8: "TV 8"
    })
    client.start = AsyncMock()
    client.stop = AsyncMock()
    return client


@pytest.fixture
def client_with_mock(mock_matrix_client):
    """Create a test client with mocked matrix client."""
    with patch("app.main.MatrixClient", return_value=mock_matrix_client):
        with patch("app.dependencies.get_matrix_client", return_value=mock_matrix_client):
            with TestClient(app) as client:
                yield client


def test_root_endpoint(client_with_mock):
    """Test root endpoint returns API info."""
    response = client_with_mock.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "HDMI Matrix Proxy"
    assert "version" in data
    assert "docs" in data


def test_liveness_probe(client_with_mock):
    """Test liveness probe endpoint."""
    response = client_with_mock.get("/healthz/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_readiness_probe(client_with_mock):
    """Test readiness probe endpoint."""
    response = client_with_mock.get("/healthz/ready")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "matrix_connected" in data
    assert "uptime_seconds" in data


def test_get_status(client_with_mock):
    """Test status endpoint."""
    response = client_with_mock.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "connection" in data
    assert "url" in data


def test_get_routing(client_with_mock):
    """Test get all routing state."""
    response = client_with_mock.get("/api/routing")
    assert response.status_code == 200
    data = response.json()
    assert "outputs" in data
    assert len(data["outputs"]) == 8


def test_get_output_routing(client_with_mock):
    """Test get specific output routing."""
    response = client_with_mock.get("/api/routing/output/1")
    assert response.status_code == 200
    data = response.json()
    assert data["output"] == 1


def test_set_output_routing(client_with_mock, mock_matrix_client):
    """Test set output routing."""
    response = client_with_mock.post(
        "/api/routing/output/1",
        json={"input": 3}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["output"] == 1
    assert data["input"] == 3
    
    # Verify the mock was called correctly
    mock_matrix_client.set_routing.assert_called_once_with(input_num=3, output_num=1)


def test_set_output_routing_by_name(client_with_mock, mock_matrix_client):
    """Test set output routing using input name."""
    response = client_with_mock.post(
        "/api/routing/output/1",
        json={"input": "Input C"}  # Name maps to input 3
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["output"] == 1
    assert data["input"] == 3  # Resolved from name
    assert data["input_name"] == "Input C"
    assert data["output_name"] == "TV 1"
    
    mock_matrix_client.set_routing.assert_called_once_with(input_num=3, output_num=1)


def test_set_output_routing_by_name_case_insensitive(client_with_mock, mock_matrix_client):
    """Test that name matching is case-insensitive."""
    response = client_with_mock.post(
        "/api/routing/output/2",
        json={"input": "input c"}  # Lowercase
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["input"] == 3


def test_set_output_routing_invalid_name(client_with_mock):
    """Test set output routing with invalid input name."""
    response = client_with_mock.post(
        "/api/routing/output/1",
        json={"input": "Nonexistent Device"}
    )
    assert response.status_code == 400
    data = response.json()
    assert "not found" in data["detail"].lower()


def test_set_output_routing_invalid_input(client_with_mock):
    """Test set output routing with invalid input number."""
    response = client_with_mock.post(
        "/api/routing/output/1",
        json={"input": 99}
    )
    assert response.status_code == 400  # Now handled by our validation


def test_set_output_routing_invalid_output(client_with_mock):
    """Test set output routing with invalid output."""
    response = client_with_mock.post(
        "/api/routing/output/99",
        json={"input": 1}
    )
    assert response.status_code == 422  # Validation error


def test_set_preset_routing(client_with_mock, mock_matrix_client):
    """Test set preset routing."""
    mappings = {1: 1, 2: 2, 3: 3}
    response = client_with_mock.post(
        "/api/routing/preset",
        json={"mappings": mappings}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["applied"]) == 3
    assert len(data["failed"]) == 0


def test_set_preset_routing_with_names(client_with_mock, mock_matrix_client):
    """Test set preset routing using input names."""
    mappings = {1: "Input A", 2: "Input B", 3: "Input C"}
    response = client_with_mock.post(
        "/api/routing/preset",
        json={"mappings": mappings}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["applied"]) == 3
    # Verify names were resolved to numbers
    assert data["applied"]["1"] == 1
    assert data["applied"]["2"] == 2
    assert data["applied"]["3"] == 3


def test_set_preset_routing_mixed(client_with_mock, mock_matrix_client):
    """Test set preset routing with mixed names and numbers."""
    mappings = {1: "Input A", 2: 2, 3: "Input C"}
    response = client_with_mock.post(
        "/api/routing/preset",
        json={"mappings": mappings}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["applied"]["1"] == 1
    assert data["applied"]["2"] == 2
    assert data["applied"]["3"] == 3


def test_set_preset_routing_invalid_name(client_with_mock, mock_matrix_client):
    """Test set preset routing with invalid input name."""
    mappings = {1: "Input A", 2: "Bad Name"}
    response = client_with_mock.post(
        "/api/routing/preset",
        json={"mappings": mappings}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False  # Partial failure
    assert len(data["applied"]) == 1
    assert len(data["failed"]) == 1
    assert "2" in data["failed"]


def test_set_preset_routing_with_output_names(client_with_mock, mock_matrix_client):
    """Test set preset routing using output names as keys."""
    mappings = {"TV 1": "Input A", "TV 2": "Input B"}
    response = client_with_mock.post(
        "/api/routing/preset",
        json={"mappings": mappings}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["applied"]) == 2
    # Verify names were resolved to numbers
    assert data["applied"]["1"] == 1
    assert data["applied"]["2"] == 2


def test_set_preset_routing_mixed_output_names(client_with_mock, mock_matrix_client):
    """Test set preset routing with mixed output names and numbers."""
    mappings = {"TV 1": "Input A", "2": "Input B", 3: "Input C"}
    response = client_with_mock.post(
        "/api/routing/preset",
        json={"mappings": mappings}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["applied"]) == 3


def test_openapi_docs_available(client_with_mock):
    """Test that OpenAPI docs are available."""
    response = client_with_mock.get("/docs")
    assert response.status_code == 200
    
    response = client_with_mock.get("/openapi.json")
    assert response.status_code == 200


def test_routing_includes_custom_names(client_with_mock):
    """Test that routing endpoint includes custom names."""
    response = client_with_mock.get("/api/routing")
    assert response.status_code == 200
    data = response.json()
    
    # Check that names dictionaries are present
    assert "input_names" in data
    assert "output_names" in data
    assert len(data["input_names"]) == 8
    assert len(data["output_names"]) == 8
    
    # Check specific names
    assert data["input_names"]["1"] == "Input A"
    assert data["output_names"]["1"] == "TV 1"
    
    # Check that outputs include names
    assert len(data["outputs"]) == 8
    first_output = data["outputs"][0]
    assert "output_name" in first_output
    assert first_output["output_name"] == "TV 1"


def test_output_routing_includes_names(client_with_mock):
    """Test that specific output routing includes names."""
    response = client_with_mock.get("/api/routing/output/1")
    assert response.status_code == 200
    data = response.json()
    
    assert "output_name" in data
    assert data["output_name"] == "TV 1"
    assert data["output"] == 1


def test_get_inputs(client_with_mock):
    """Test get all input names endpoint."""
    response = client_with_mock.get("/api/inputs")
    assert response.status_code == 200
    data = response.json()
    
    assert "inputs" in data
    assert "names" in data
    assert len(data["inputs"]) == 8
    assert len(data["names"]) == 8
    
    # Check structure
    first_input = data["inputs"][0]
    assert "number" in first_input
    assert "name" in first_input
    assert first_input["number"] == 1
    assert first_input["name"] == "Input A"
    
    # Check names list (for dropdown options)
    assert "Input A" in data["names"]
    assert "Input H" in data["names"]


def test_get_outputs(client_with_mock):
    """Test get all output names endpoint."""
    response = client_with_mock.get("/api/outputs")
    assert response.status_code == 200
    data = response.json()
    
    assert "outputs" in data
    assert "names" in data
    assert len(data["outputs"]) == 8
    assert len(data["names"]) == 8
    
    # Check structure
    first_output = data["outputs"][0]
    assert "number" in first_output
    assert "name" in first_output
    assert first_output["number"] == 1
    assert first_output["name"] == "TV 1"
    
    # Check names list
    assert "TV 1" in data["names"]
    assert "TV 8" in data["names"]


def test_set_routing_response_includes_names(client_with_mock, mock_matrix_client):
    """Test that set routing response includes names."""
    response = client_with_mock.post(
        "/api/routing/output/1",
        json={"input": 3}
    )
    assert response.status_code == 200
    data = response.json()
    
    assert data["input_name"] == "Input C"
    assert data["output_name"] == "TV 1"
    assert "Routed Input C to TV 1" in data["message"]


def test_get_output_routing_by_name(client_with_mock):
    """Test get output routing using output name in URL."""
    response = client_with_mock.get("/api/routing/output/TV%201")
    assert response.status_code == 200
    data = response.json()
    assert data["output"] == 1
    assert data["output_name"] == "TV 1"


def test_set_output_routing_by_output_name(client_with_mock, mock_matrix_client):
    """Test set output routing using output name in URL."""
    response = client_with_mock.post(
        "/api/routing/output/TV%202",
        json={"input": "Input C"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["output"] == 2
    assert data["output_name"] == "TV 2"
    assert data["input"] == 3
    assert data["input_name"] == "Input C"
    
    mock_matrix_client.set_routing.assert_called_once_with(input_num=3, output_num=2)


def test_set_output_routing_invalid_output_name(client_with_mock):
    """Test set output routing with invalid output name."""
    response = client_with_mock.post(
        "/api/routing/output/Nonexistent%20TV",
        json={"input": 1}
    )
    assert response.status_code == 400
    data = response.json()
    assert "not found" in data["detail"].lower()
