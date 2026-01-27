"""HTTP client for HDMI matrix communication."""

import asyncio
from datetime import UTC, datetime

import httpx
import structlog

from app.models import ConnectionState

log = structlog.get_logger()


class MatrixClient:
    """HTTP client for communicating with the MT-VIKI MT-H8M88 HDMI matrix."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        verify_ssl: bool = False,
        health_interval: int = 30,
    ):
        """Initialize the matrix client.

        Args:
            base_url: Base URL of the matrix web interface (with or without http://)
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
            health_interval: Interval between health checks in seconds
        """
        # Ensure base_url has a protocol
        if not base_url.startswith(("http://", "https://")):
            base_url = f"http://{base_url}"
        
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.health_interval = health_interval

        self._client: httpx.AsyncClient | None = None
        self._connection_state = ConnectionState.DISCONNECTED
        self._last_command_time: datetime | None = None
        self._last_response: str | None = None
        self._health_task: asyncio.Task | None = None
        self._running = False

    @property
    def connection_state(self) -> ConnectionState:
        """Get current connection state."""
        return self._connection_state

    @property
    def last_command_time(self) -> datetime | None:
        """Get timestamp of last successful command."""
        return self._last_command_time

    @property
    def last_response(self) -> str | None:
        """Get last response from matrix."""
        return self._last_response

    async def start(self) -> None:
        """Start the matrix client and health monitoring."""
        if self._running:
            log.warning("matrix_client_already_running")
            return

        log.info("starting_matrix_client", base_url=self.base_url)
        self._running = True

        # Create HTTP client
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            verify=self.verify_ssl,
        )

        # Test initial connection
        await self._check_health()

        # Start health monitoring
        self._health_task = asyncio.create_task(self._health_monitor())

    async def stop(self) -> None:
        """Stop the matrix client and cleanup."""
        log.info("stopping_matrix_client")
        self._running = False

        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.aclose()
            self._client = None

        self._connection_state = ConnectionState.DISCONNECTED

    async def send_command(self, cmd: str) -> str:
        """Send a command to the matrix.

        Args:
            cmd: Command string (e.g., "SW+1+1" to route input 1 to output 1)

        Returns:
            Response text from the matrix

        Raises:
            RuntimeError: If client is not initialized or connection fails
        """
        if not self._client or not self._running:
            raise RuntimeError("Matrix client not initialized")

        endpoint = f"{self.base_url}/form-system-cmd.cgi"
        data = {"cmd": cmd}

        log.debug("sending_matrix_command", cmd=cmd, endpoint=endpoint)

        try:
            response = await self._client.post(endpoint, data=data)
            response.raise_for_status()

            self._connection_state = ConnectionState.CONNECTED
            self._last_command_time = datetime.now(UTC)
            self._last_response = response.text

            log.info(
                "matrix_command_success",
                cmd=cmd,
                status_code=response.status_code,
                response_length=len(response.text),
            )

            return response.text

        except httpx.HTTPStatusError as e:
            self._connection_state = ConnectionState.ERROR
            log.error(
                "matrix_command_http_error",
                cmd=cmd,
                status_code=e.response.status_code,
                error=str(e),
            )
            raise RuntimeError(f"HTTP error: {e.response.status_code}") from e

        except httpx.RequestError as e:
            self._connection_state = ConnectionState.ERROR
            log.error("matrix_command_request_error", cmd=cmd, error=str(e))
            raise RuntimeError(f"Request failed: {e}") from e

    async def set_routing(self, input_num: int, output_num: int) -> bool:
        """Route an input to an output.

        Args:
            input_num: Input number (1-8)
            output_num: Output number (1-8)

        Returns:
            True if successful

        Raises:
            ValueError: If input or output numbers are invalid
            RuntimeError: If command fails
        """
        if not 1 <= input_num <= 8:
            raise ValueError(f"Invalid input number: {input_num} (must be 1-8)")
        if not 1 <= output_num <= 8:
            raise ValueError(f"Invalid output number: {output_num} (must be 1-8)")

        cmd = f"SW+{input_num}+{output_num}"
        await self.send_command(cmd)
        return True

    async def get_routing_state(self) -> dict[int, int]:
        """Get current routing state for all outputs.

        Note: The MT-VIKI matrix may not have a status query command.
        This is a placeholder that returns an empty dict. You may need to
        track state locally or discover the actual status command.

        Returns:
            Dictionary mapping output number to input number
        """
        # TODO: Investigate if matrix has a status query command
        # For now, return empty dict - we'll need to track state locally
        log.warning("get_routing_state_not_implemented")
        return {}

    async def get_input_names(self) -> dict[int, str]:
        """Get custom names for all inputs (1-8).

        Returns:
            Dictionary mapping input number to custom name.
            Falls back to generic names if retrieval fails.
        """
        if not self._client or not self._running:
            log.warning("matrix_client_not_initialized", action="get_input_names")
            return self._get_default_input_names()

        endpoint = f"{self.base_url}/form-system-info.cgi"
        data = {"in_name": "0"}

        try:
            response = await self._client.post(endpoint, data=data)
            response.raise_for_status()

            result = response.json()
            if "in_name" in result and isinstance(result["in_name"], list):
                names = result["in_name"]
                # Convert list to dict (1-indexed)
                name_dict = {i + 1: names[i] for i in range(min(len(names), 8))}
                log.debug("retrieved_input_names", count=len(name_dict))
                return name_dict
            else:
                log.warning("invalid_input_names_response", response=result)
                return self._get_default_input_names()

        except Exception as e:
            log.error("failed_to_get_input_names", error=str(e))
            return self._get_default_input_names()

    async def get_output_names(self) -> dict[int, str]:
        """Get custom names for all outputs (1-8).

        Returns:
            Dictionary mapping output number to custom name.
            Falls back to generic names if retrieval fails.
        """
        if not self._client or not self._running:
            log.warning("matrix_client_not_initialized", action="get_output_names")
            return self._get_default_output_names()

        endpoint = f"{self.base_url}/form-system-info.cgi"
        data = {"out_name": "0"}

        try:
            response = await self._client.post(endpoint, data=data)
            response.raise_for_status()

            result = response.json()
            if "out_name" in result and isinstance(result["out_name"], list):
                names = result["out_name"]
                # Convert list to dict (1-indexed)
                name_dict = {i + 1: names[i] for i in range(min(len(names), 8))}
                log.debug("retrieved_output_names", count=len(name_dict))
                return name_dict
            else:
                log.warning("invalid_output_names_response", response=result)
                return self._get_default_output_names()

        except Exception as e:
            log.error("failed_to_get_output_names", error=str(e))
            return self._get_default_output_names()

    def _get_default_input_names(self) -> dict[int, str]:
        """Get default input names as fallback.

        Returns:
            Dictionary with generic input names
        """
        return {i: f"HDMI {i}" for i in range(1, 9)}

    def _get_default_output_names(self) -> dict[int, str]:
        """Get default output names as fallback.

        Returns:
            Dictionary with generic output names
        """
        return {i: f"Output {i}" for i in range(1, 9)}

    async def _check_health(self) -> bool:
        """Check if matrix is reachable.

        Returns:
            True if matrix is reachable
        """
        if not self._client:
            self._connection_state = ConnectionState.DISCONNECTED
            return False

        try:
            # Try to access the base URL
            response = await self._client.get(self.base_url)
            response.raise_for_status()

            self._connection_state = ConnectionState.CONNECTED
            log.debug("matrix_health_check_success")
            return True

        except (httpx.HTTPError, httpx.RequestError) as e:
            self._connection_state = ConnectionState.ERROR
            log.warning("matrix_health_check_failed", error=str(e))
            return False

    async def _health_monitor(self) -> None:
        """Background task to monitor matrix health."""
        log.info("starting_health_monitor", interval=self.health_interval)

        while self._running:
            try:
                await asyncio.sleep(self.health_interval)
                await self._check_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("health_monitor_error", error=str(e))
