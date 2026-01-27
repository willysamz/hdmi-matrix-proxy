"""Matrix client tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.matrix_client import MatrixClient
from app.models import ConnectionState


@pytest.fixture
def matrix_client():
    """Create a matrix client instance."""
    return MatrixClient(
        base_url="http://test-matrix.local",
        timeout=5.0,
        verify_ssl=False,
        health_interval=30,
    )


@pytest.mark.asyncio
async def test_client_initialization(matrix_client):
    """Test client initializes with correct state."""
    assert matrix_client.base_url == "http://test-matrix.local"
    assert matrix_client.timeout == 5.0
    assert matrix_client.connection_state == ConnectionState.DISCONNECTED
    assert matrix_client.last_command_time is None


@pytest.mark.asyncio
async def test_set_routing_validates_input(matrix_client):
    """Test that set_routing validates input numbers."""
    with pytest.raises(ValueError, match="Invalid input number"):
        await matrix_client.set_routing(0, 1)
    
    with pytest.raises(ValueError, match="Invalid input number"):
        await matrix_client.set_routing(9, 1)


@pytest.mark.asyncio
async def test_set_routing_validates_output(matrix_client):
    """Test that set_routing validates output numbers."""
    with pytest.raises(ValueError, match="Invalid output number"):
        await matrix_client.set_routing(1, 0)
    
    with pytest.raises(ValueError, match="Invalid output number"):
        await matrix_client.set_routing(1, 9)


@pytest.mark.asyncio
async def test_send_command_requires_client(matrix_client):
    """Test that send_command raises error if client not initialized."""
    with pytest.raises(RuntimeError, match="Matrix client not initialized"):
        await matrix_client.send_command("SW+1+1")


@pytest.mark.asyncio
async def test_send_command_success():
    """Test successful command sending."""
    client = MatrixClient(
        base_url="http://test-matrix.local",
        timeout=5.0,
        verify_ssl=False,
        health_interval=30,
    )
    
    # Mock the httpx client
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = "OK"
    mock_response.raise_for_status = AsyncMock()
    
    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_http_client.aclose = AsyncMock()
    
    with patch("httpx.AsyncClient", return_value=mock_http_client):
        await client.start()
        
        try:
            result = await client.send_command("SW+1+1")
            assert result == "OK"
            assert client.connection_state == ConnectionState.CONNECTED
            assert client.last_command_time is not None
            
            # Verify the POST was called correctly
            mock_http_client.post.assert_called_with(
                "http://test-matrix.local/form-system-cmd.cgi",
                data={"cmd": "SW+1+1"}
            )
        finally:
            await client.stop()


@pytest.mark.asyncio
async def test_set_routing_calls_send_command():
    """Test that set_routing calls send_command with correct format."""
    client = MatrixClient(
        base_url="http://test-matrix.local",
        timeout=5.0,
        verify_ssl=False,
        health_interval=30,
    )
    
    # Mock the httpx client
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = "OK"
    mock_response.raise_for_status = AsyncMock()
    
    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_http_client.aclose = AsyncMock()
    
    with patch("httpx.AsyncClient", return_value=mock_http_client):
        await client.start()
        
        try:
            result = await client.set_routing(input_num=3, output_num=5)
            assert result is True
            
            # Verify the command was formatted correctly
            mock_http_client.post.assert_called_with(
                "http://test-matrix.local/form-system-cmd.cgi",
                data={"cmd": "SW 3 5"}
            )
        finally:
            await client.stop()


@pytest.mark.asyncio
async def test_get_input_names():
    """Test retrieving input names from matrix."""
    client = MatrixClient(
        base_url="http://test-matrix.local",
        timeout=5.0,
        verify_ssl=False,
        health_interval=30,
    )
    
    # Mock the httpx client with names response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(
        return_value={"in_name": ["Input A", "Input B", "Input C", "Input D", 
                                   "Input E", "Input F", "Input G", "Input H"]}
    )
    mock_response.raise_for_status = MagicMock()
    
    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_http_client.aclose = AsyncMock()
    
    with patch("httpx.AsyncClient", return_value=mock_http_client):
        await client.start()
        
        try:
            names = await client.get_input_names()
            assert len(names) == 8
            assert names[1] == "Input A"
            assert names[8] == "Input H"
            
            # Verify correct endpoint and data
            calls = [call for call in mock_http_client.post.call_args_list 
                    if "form-system-info.cgi" in str(call)]
            assert len(calls) > 0
        finally:
            await client.stop()


@pytest.mark.asyncio
async def test_get_output_names():
    """Test retrieving output names from matrix."""
    client = MatrixClient(
        base_url="http://test-matrix.local",
        timeout=5.0,
        verify_ssl=False,
        health_interval=30,
    )
    
    # Mock the httpx client with names response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(
        return_value={"out_name": ["TV 1", "TV 2", "TV 3", "TV 4",
                                    "TV 5", "TV 6", "TV 7", "TV 8"]}
    )
    mock_response.raise_for_status = MagicMock()
    
    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_http_client.aclose = AsyncMock()
    
    with patch("httpx.AsyncClient", return_value=mock_http_client):
        await client.start()
        
        try:
            names = await client.get_output_names()
            assert len(names) == 8
            assert names[1] == "TV 1"
            assert names[8] == "TV 8"
        finally:
            await client.stop()


@pytest.mark.asyncio
async def test_get_names_fallback():
    """Test that default names are returned when retrieval fails."""
    client = MatrixClient(
        base_url="http://test-matrix.local",
        timeout=5.0,
        verify_ssl=False,
        health_interval=30,
    )
    
    # Mock the httpx client to return error
    mock_response = AsyncMock()
    mock_response.status_code = 500
    mock_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "Server error", request=MagicMock(), response=mock_response
    ))
    
    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_http_client.aclose = AsyncMock()
    
    with patch("httpx.AsyncClient", return_value=mock_http_client):
        await client.start()
        
        try:
            # Should fall back to defaults
            input_names = await client.get_input_names()
            output_names = await client.get_output_names()
            
            assert len(input_names) == 8
            assert len(output_names) == 8
            assert input_names[1] == "HDMI 1"
            assert output_names[1] == "Output 1"
        finally:
            await client.stop()


@pytest.mark.asyncio
async def test_get_routing_state():
    """Test retrieving current routing state from matrix."""
    client = MatrixClient(
        base_url="http://test-matrix.local",
        timeout=5.0,
        verify_ssl=False,
        health_interval=30,
    )
    
    # Mock the routing state response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(
        return_value={
            "head": {"info_var": 87, "mx_type": 8},
            "data": {
                "video": {
                    "vsw": [0, 1, 2, 3, 4, 5, 6, 7],
                    "outen": [1, 1, 1, 1, 1, 1, 1, 1]
                }
            }
        }
    )
    mock_response.raise_for_status = MagicMock()
    
    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_http_client.aclose = AsyncMock()
    
    with patch("httpx.AsyncClient", return_value=mock_http_client):
        await client.start()
        
        try:
            routing = await client.get_routing_state()
            
            # Verify routing state (0-indexed from API becomes 1-indexed)
            assert len(routing) == 8
            assert routing[1] == 1  # Output 1 -> Input 1
            assert routing[2] == 2  # Output 2 -> Input 2
            assert routing[8] == 8  # Output 8 -> Input 8
            
            # Verify correct endpoint and data
            calls = [call for call in mock_http_client.post.call_args_list 
                    if "form-system-info.cgi" in str(call)]
            assert len(calls) > 0
        finally:
            await client.stop()
