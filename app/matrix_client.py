"""HTTP client for HDMI matrix communication."""

import asyncio
from datetime import UTC, datetime

import httpx
import structlog

from app.models import ConnectionState, EdidSource

log = structlog.get_logger()

# EDID command families and the write-side ceiling for each, as measured on
# this MT-VIKI unit on 2026-09-24. These bound what we will *send*; the
# catalogue probe in `app/edid.py` discovers the real ceiling by reading
# until the device answers ERROR, because these numbers are this unit's.
EDID_INDEX_MAX: dict[str, int] = {"out": 8, "sys": 10, "user": 5}

# `@EDID-SW-<FAMILY>:<index>,<input>` — the family token per source.
_EDID_CMD_FAMILY: dict[str, str] = {"out": "OUT", "sys": "SYS", "user": "USER"}

# `form-system-info.cgi` read parameter per source.
_EDID_READ_PARAM: dict[str, str] = {
    "out": "out_edid",
    "sys": "sys_edid",
    "user": "user_edid",
}

# The device reports a failed EDID read with this literal response body.
EDID_ERROR_BODY = "ERROR"

# Upper bound on how far the catalogue probe may walk a family before giving
# up, in case a unit never answers ERROR. Purely a safety stop.
EDID_PROBE_LIMIT = 32


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

        cmd = f"SW {input_num} {output_num}"
        await self.send_command(cmd)
        return True

    async def set_input_edid(self, source: EdidSource, index: int, input_num: int | None) -> bool:
        """Assign an EDID to one input, or to ALL inputs when `input_num` is None.

        Builds one of the three documented commands:

            @EDID-SW-OUT:<out>,<in>    EDID read from output <out>
            @EDID-SW-SYS:<n>,<in>      built-in EDID <n>
            @EDID-SW-USER:<n>,<in>     user slot <n>

        `<in>` = 0 is the device's "all inputs" form, which is what
        `input_num=None` sends. Inputs are 1-based.

        Everything is validated before anything is sent: this device answers
        `OK` to commands it then silently ignores, so an `OK` is not
        confirmation and a bad index would look like a success.

        Note there is **no way to read back which EDID an input is using** —
        nothing returned here or elsewhere reports the assignment.

        Args:
            source: "out", "sys" or "user"
            index: output number (1-8), built-in slot (1-10) or user slot (1-5)
            input_num: input 1-8, or None for all inputs

        Returns:
            True if the command was accepted by the HTTP layer.

        Raises:
            ValueError: If the source, index or input number is out of range
            RuntimeError: If the command fails
        """
        if source not in _EDID_CMD_FAMILY:
            raise ValueError(
                f"Invalid EDID source: {source!r} (must be one of " f"{sorted(_EDID_CMD_FAMILY)})"
            )
        max_index = EDID_INDEX_MAX[source]
        if not 1 <= index <= max_index:
            raise ValueError(f"Invalid {source} EDID index: {index} (must be 1-{max_index})")
        if input_num is not None and not 1 <= input_num <= 8:
            raise ValueError(f"Invalid input number: {input_num} (must be 1-8 or None)")

        target = 0 if input_num is None else input_num
        cmd = f"@EDID-SW-{_EDID_CMD_FAMILY[source]}:{index},{target}"
        await self.send_command(cmd)
        log.info("matrix_edid_assigned", source=source, index=index, input=target)
        return True

    async def read_edid(self, source: EdidSource, index: int) -> dict | None:
        """Read one EDID slot: `{'name', 'hex'}`, or None when unreadable.

        `sys_edid` and `user_edid` read fine on this unit. `out_edid` returns
        the literal body `ERROR` here whether or not you are logged in — that
        is normal, not a fault and not a permissions problem, so a failed read
        is **never** an exception. Reading past the last slot of a family also
        returns `ERROR`, which is how the catalogue probe finds the ceiling.

        Args:
            source: "out", "sys" or "user"
            index: 1-based slot number

        Returns:
            {"name": str, "hex": str} or None when the device cannot read it

        Raises:
            ValueError: If the source is unknown or the index is below 1
        """
        if source not in _EDID_READ_PARAM:
            raise ValueError(
                f"Invalid EDID source: {source!r} (must be one of " f"{sorted(_EDID_READ_PARAM)})"
            )
        if index < 1:
            raise ValueError(f"Invalid EDID index: {index} (must be >= 1)")

        if not self._client or not self._running:
            log.warning("matrix_client_not_initialized", action="read_edid")
            return None

        endpoint = f"{self.base_url}/form-system-info.cgi"
        data = {_EDID_READ_PARAM[source]: str(index)}

        try:
            response = await self._client.post(endpoint, data=data)
            response.raise_for_status()

            if (response.text or "").strip().upper() == EDID_ERROR_BODY:
                log.debug("edid_read_error_body", source=source, index=index)
                return None

            result = response.json()
            name = result.get("edid_name")
            hex_blob = result.get("edid_hex")
            if name is None and hex_blob is None:
                log.debug("edid_read_empty", source=source, index=index)
                return None
            return {"name": name, "hex": hex_blob}

        except Exception as e:
            # A failed EDID read is routine on this device; report it as
            # "unreadable" rather than propagating.
            log.debug("edid_read_failed", source=source, index=index, error=str(e))
            return None

    async def get_routing_state(self) -> dict[int, int]:
        """Get current routing state for all outputs.

        Retrieves the routing state by querying the matrix web interface.
        The 'vsw' array contains 8 values (one per output), where each
        value is the input number (0-7) routed to that output.

        Returns:
            Dictionary mapping output number (1-8) to input number (1-8)
        """
        if not self._client or not self._running:
            log.warning("matrix_client_not_initialized", action="get_routing_state")
            return {}

        endpoint = f"{self.base_url}/form-system-info.cgi"
        data = {"video": "0"}

        try:
            response = await self._client.post(endpoint, data=data)
            response.raise_for_status()

            result = response.json()
            vsw = result.get("data", {}).get("video", {}).get("vsw", [])

            if not vsw or len(vsw) != 8:
                log.warning("invalid_routing_response", vsw=vsw)
                return {}

            # Convert 0-indexed array to 1-indexed dict
            # vsw[0] = 0 means output 1 has input 1
            routing = {}
            for output_idx, input_idx in enumerate(vsw):
                routing[output_idx + 1] = input_idx + 1

            log.info("routing_state_retrieved", count=len(routing))
            return routing

        except Exception as e:
            log.error("failed_to_get_routing_state", error=str(e))
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
