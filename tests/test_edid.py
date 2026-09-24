"""Tests for per-input EDID control.

Covers the three layers:
- `MatrixClient.set_input_edid` / `read_edid` — exact command strings, the
  `,0` all-inputs form, range validation before any HTTP call, and the
  device's literal `ERROR` body mapping to `None`.
- `EdidCatalogue` — startup probe that stops at the first `ERROR` per family.
- The HA surface — discovery payload + the controller's command handler,
  which publishes only what it just set and never polls.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.controller import Controller, ControllerError
from app.discovery import input_edid_select_payload
from app.edid import EDID_UNKNOWN_PAYLOAD, EdidCatalogue, EdidOption
from app.matrix_client import MatrixClient

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _mock_http(post_side_effect=None, post_return=None):
    """Build a mocked httpx.AsyncClient the way the existing tests do."""
    generic = AsyncMock()
    generic.status_code = 200
    generic.text = "OK"
    generic.raise_for_status = MagicMock()

    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    if post_side_effect is not None:
        mock_http_client.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock_http_client.post = AsyncMock(return_value=post_return or generic)
    mock_http_client.get = AsyncMock(return_value=generic)
    mock_http_client.aclose = AsyncMock()
    return mock_http_client


def _response(text: str, json_value=None):
    resp = AsyncMock()
    resp.status_code = 200
    resp.text = text
    resp.raise_for_status = MagicMock()
    if json_value is None:
        resp.json = MagicMock(side_effect=ValueError("not json"))
    else:
        resp.json = MagicMock(return_value=json_value)
    return resp


async def _started_client(mock_http_client) -> MatrixClient:
    client = MatrixClient(base_url="http://test-matrix.local")
    with patch("httpx.AsyncClient", return_value=mock_http_client):
        await client.start()
    return client


def _commands(mock_http_client) -> list[str]:
    """Every `cmd=` string POSTed to form-system-cmd.cgi."""
    out = []
    for call in mock_http_client.post.call_args_list:
        args, kwargs = call
        data = kwargs.get("data") or {}
        if "cmd" in data:
            out.append(data["cmd"])
    return out


# --------------------------------------------------------------------------
# Task 2 — MatrixClient.set_input_edid
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "index", "input_num", "expected"),
    [
        ("sys", 8, 6, "@EDID-SW-SYS:8,6"),
        ("user", 1, 6, "@EDID-SW-USER:1,6"),
        ("out", 3, 2, "@EDID-SW-OUT:3,2"),
        ("sys", 1, 1, "@EDID-SW-SYS:1,1"),
    ],
)
@pytest.mark.asyncio
async def test_set_input_edid_builds_documented_command(source, index, input_num, expected):
    http = _mock_http()
    client = await _started_client(http)
    try:
        assert await client.set_input_edid(source, index, input_num) is True
        assert _commands(http) == [expected]
        http.post.assert_called_with(
            "http://test-matrix.local/form-system-cmd.cgi",
            data={"cmd": expected},
        )
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_set_input_edid_none_means_all_inputs():
    """`input_num=None` is the device's all-inputs form: `,0`."""
    http = _mock_http()
    client = await _started_client(http)
    try:
        await client.set_input_edid("sys", 7, None)
        assert _commands(http) == ["@EDID-SW-SYS:7,0"]
    finally:
        await client.stop()


@pytest.mark.parametrize(
    ("source", "index", "input_num"),
    [
        ("sys", 0, 1),
        ("sys", 11, 1),
        ("user", 0, 1),
        ("user", 6, 1),
        ("out", 0, 1),
        ("out", 9, 1),
        ("sys", 1, 0),
        ("sys", 1, 9),
    ],
)
@pytest.mark.asyncio
async def test_set_input_edid_rejects_out_of_range_before_any_request(source, index, input_num):
    """The device answers OK to things it then ignores, so validate first."""
    http = _mock_http()
    client = await _started_client(http)
    try:
        http.post.reset_mock()
        with pytest.raises(ValueError):
            await client.set_input_edid(source, index, input_num)
        assert http.post.call_count == 0
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_set_input_edid_rejects_unknown_source_before_any_request():
    http = _mock_http()
    client = await _started_client(http)
    try:
        http.post.reset_mock()
        with pytest.raises(ValueError):
            await client.set_input_edid("bogus", 1, 1)  # type: ignore[arg-type]
        assert http.post.call_count == 0
    finally:
        await client.stop()


# --------------------------------------------------------------------------
# Task 2 — MatrixClient.read_edid
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_edid_returns_name_and_hex():
    resp = _response(
        '{"edid_name":"UHD4K60","edid_hex":"00FFFF"}',
        {"edid_name": "UHD4K60", "edid_hex": "00FFFF"},
    )
    http = _mock_http(post_return=resp)
    client = await _started_client(http)
    try:
        result = await client.read_edid("sys", 8)
        assert result == {"name": "UHD4K60", "hex": "00FFFF"}
        http.post.assert_called_with(
            "http://test-matrix.local/form-system-info.cgi",
            data={"sys_edid": "8"},
        )
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_read_edid_user_uses_user_param():
    resp = _response(
        '{"edid_name":"Beyond TV","edid_hex":"AA"}',
        {"edid_name": "Beyond TV", "edid_hex": "AA"},
    )
    http = _mock_http(post_return=resp)
    client = await _started_client(http)
    try:
        await client.read_edid("user", 2)
        http.post.assert_called_with(
            "http://test-matrix.local/form-system-info.cgi",
            data={"user_edid": "2"},
        )
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_read_edid_error_body_returns_none_not_exception():
    """`out_edid` errors on this unit as a matter of course — never raise."""
    http = _mock_http(post_return=_response("ERROR"))
    client = await _started_client(http)
    try:
        assert await client.read_edid("out", 1) is None
        assert await client.read_edid("sys", 11) is None
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_read_edid_transport_failure_returns_none():
    http = _mock_http(post_side_effect=httpx.ConnectError("boom"))
    client = await _started_client(http)
    try:
        assert await client.read_edid("sys", 1) is None
    finally:
        await client.stop()


# --------------------------------------------------------------------------
# Task 3 — the catalogue probe
# --------------------------------------------------------------------------


class _FakeMatrix:
    """Reads that mirror the measured unit: SYS 1..sys_max, USER 1..user_max."""

    def __init__(self, sys_names: dict[int, str], user_names: dict[int, str]):
        self.sys_names = sys_names
        self.user_names = user_names
        self.reads: list[tuple[str, int]] = []
        self.writes: list[tuple[str, int, int | None]] = []

    async def read_edid(self, source, index):
        self.reads.append((source, index))
        table = self.sys_names if source == "sys" else self.user_names
        if index not in table:
            return None
        return {"name": table[index], "hex": f"{source}{index}hex"}

    async def set_input_edid(self, source, index, input_num):
        self.writes.append((source, index, input_num))
        return True


def _unit_like_matrix() -> _FakeMatrix:
    sys_names = dict.fromkeys(range(1, 7), "HDMI Matrix")
    sys_names[7] = "UHD4K30"
    sys_names[8] = "UHD4K60"
    sys_names[9] = "UHD8K60"
    sys_names[10] = "UHD8K60"
    user_names = {
        1: "Beyond TV",
        2: "Beyond TV",
        3: "HDMI Matrix",
        4: "HDMI Matrix",
        5: "HDMI Matrix",
    }
    return _FakeMatrix(sys_names, user_names)


@pytest.mark.asyncio
async def test_catalogue_stops_at_first_error_per_family():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)

    sys_reads = [i for src, i in matrix.reads if src == "sys"]
    user_reads = [i for src, i in matrix.reads if src == "user"]
    # Probed 1..10 then stopped on the 11th ERROR; never went to 12.
    assert sys_reads == list(range(1, 12))
    assert user_reads == list(range(1, 7))

    assert [o.index for o in cat.options if o.source == "sys"] == list(range(1, 11))
    assert [o.index for o in cat.options if o.source == "user"] == list(range(1, 6))


@pytest.mark.asyncio
async def test_catalogue_ceiling_is_not_hardcoded_to_this_unit():
    """A unit with fewer slots stops earlier; one with more keeps going."""
    matrix = _FakeMatrix({1: "A", 2: "B"}, {1: "U"})
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)
    assert [o.index for o in cat.options if o.source == "sys"] == [1, 2]
    assert [o.index for o in cat.options if o.source == "user"] == [1]


@pytest.mark.asyncio
async def test_catalogue_labels_include_the_index():
    """Six slots share the name `HDMI Matrix`, so a name alone is ambiguous."""
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)

    labels = cat.labels
    assert "SYS 7 · UHD4K30" in labels
    assert "SYS 8 · UHD4K60" in labels
    assert "USER 1 · Beyond TV" in labels
    # every label is distinct even though names repeat
    assert len(labels) == len(set(labels))
    # outputs are offered by number only — out_edid cannot be read here
    assert "Copy from output 4" in labels


@pytest.mark.asyncio
async def test_catalogue_records_a_content_hash():
    """SYS 1-6 share a name but differ in content; the hash keeps them apart."""
    matrix = _FakeMatrix({1: "HDMI Matrix", 2: "HDMI Matrix"}, {})
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)
    hashes = [o.content_hash for o in cat.options if o.source == "sys"]
    assert all(hashes)
    assert hashes[0] != hashes[1]


@pytest.mark.asyncio
async def test_catalogue_is_cached_and_not_reprobed():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)
    first = len(matrix.reads)
    await cat.ensure_loaded(matrix)
    assert len(matrix.reads) == first


@pytest.mark.asyncio
async def test_catalogue_resolves_a_label_back_to_source_and_index():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)
    assert cat.resolve("SYS 8 · UHD4K60") == EdidOption(
        source="sys",
        index=8,
        name="UHD4K60",
        content_hash=cat.resolve("SYS 8 · UHD4K60").content_hash,
    )
    assert cat.resolve("Copy from output 2").source == "out"
    assert cat.resolve("nope") is None


@pytest.mark.asyncio
async def test_catalogue_unloaded_when_matrix_is_unreachable():
    class _Dead:
        async def read_edid(self, source, index):
            return None

    cat = EdidCatalogue()
    await cat.ensure_loaded(_Dead())
    assert cat.options == []
    assert cat.loaded is False  # retry on the next cycle


# --------------------------------------------------------------------------
# Task 4 — HA surface
# --------------------------------------------------------------------------


def test_input_edid_select_discovery_payload():
    topic, payload = input_edid_select_payload(
        discovery_prefix="homeassistant",
        device_id="hdmi_matrix",
        device_name="HDMI Matrix",
        state_topic="matrix/edid/input/6/state",
        command_topic="matrix/edid/input/6/set",
        availability_topic="matrix/bridge/available",
        input_number=6,
        input_name="PlayStation 5",
        options=["SYS 8 · UHD4K60"],
    )
    assert topic == "homeassistant/select/hdmi_matrix_input_6_edid/config"
    assert payload["object_id"] == "hdmi_matrix_input_6_edid"
    assert payload["unique_id"] == "hdmi_matrix_input_6_edid"
    assert payload["options"] == ["SYS 8 · UHD4K60"]
    assert payload["command_topic"] == "matrix/edid/input/6/set"
    # The assignment is unreadable, so the name must say so.
    assert "not read back" in payload["name"].lower()
    assert "PlayStation 5" in payload["name"]


class _FakeMqtt:
    def __init__(self):
        self.published: list[tuple[str, object, bool]] = []
        self.availability_topic = "matrix/bridge/available"

    async def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))


class _FakePoller:
    def __init__(self):
        self.polled = False

    def trigger_immediate_poll(self):
        self.polled = True


class _Settings:
    mqtt_topic_prefix = "matrix"
    ha_discovery_enabled = True
    ha_discovery_prefix = "homeassistant"
    ha_device_id = "hdmi_matrix"
    ha_device_name = "HDMI Matrix"
    poll_interval = 10.0


def _controller(matrix, catalogue):
    mqtt = _FakeMqtt()
    poller = _FakePoller()
    c = Controller(
        matrix=matrix,
        mqtt=mqtt,
        poller=poller,
        settings=_Settings(),
        edid_catalogue=catalogue,
    )
    return c, mqtt, poller


@pytest.mark.asyncio
async def test_controller_sets_edid_and_echoes_what_it_set():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)
    c, mqtt, poller = _controller(matrix, cat)

    await c.set_input_edid(6, "SYS 8 · UHD4K60")

    assert matrix.writes == [("sys", 8, 6)]
    assert ("matrix/edid/input/6/state", "SYS 8 · UHD4K60", False) in mqtt.published
    # There is nothing to poll for EDID — the poller reads routing only.
    assert poller.polled is False


@pytest.mark.asyncio
async def test_controller_rejects_an_option_not_in_the_catalogue():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)
    c, mqtt, _ = _controller(matrix, cat)

    with pytest.raises(ControllerError):
        await c.set_input_edid(6, "SYS 99 · Nope")
    assert matrix.writes == []
    assert mqtt.published == []


@pytest.mark.asyncio
async def test_controller_rejects_an_out_of_range_input():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)
    c, _, _ = _controller(matrix, cat)

    with pytest.raises(ControllerError):
        await c.set_input_edid(0, "SYS 8 · UHD4K60")
    with pytest.raises(ControllerError):
        await c.set_input_edid(9, "SYS 8 · UHD4K60")
    assert matrix.writes == []


@pytest.mark.asyncio
async def test_controller_has_no_all_inputs_target():
    """`input=None` exists on the client, but is deliberately not reachable
    from an entity — a misclick would retune every source in the house."""
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)
    c, _, _ = _controller(matrix, cat)

    with pytest.raises(ControllerError):
        await c.set_input_edid(0, "SYS 8 · UHD4K60")


@pytest.mark.asyncio
async def test_poller_publishes_edid_selects_with_unknown_state():
    from app.poller import Poller

    matrix = _unit_like_matrix()

    class _PollMatrix(_FakeMatrix):
        async def get_input_names(self):
            return {i: f"In {i}" for i in range(1, 9)}

        async def get_output_names(self):
            return {i: f"Out {i}" for i in range(1, 9)}

        async def get_routing_state(self):
            return {i: i for i in range(1, 9)}

    pm = _PollMatrix(matrix.sys_names, matrix.user_names)
    mqtt = _FakeMqtt()
    cat = EdidCatalogue()
    poller = Poller(matrix=pm, mqtt=mqtt, settings=_Settings(), edid_catalogue=cat)
    await poller.poll_once()

    topics = [t for t, _, _ in mqtt.published]
    assert "homeassistant/select/hdmi_matrix_input_6_edid/config" in topics
    # Initial state is honestly unknown — nothing has been read back.
    states = [(t, p) for t, p, _ in mqtt.published if t == "matrix/edid/input/6/state"]
    assert states == [("matrix/edid/input/6/state", EDID_UNKNOWN_PAYLOAD)]


@pytest.mark.asyncio
async def test_poller_edid_state_is_not_retained():
    """Not retained: a restart must go back to unknown rather than replay a
    value that a front-panel change may already have invalidated."""
    from app.poller import Poller

    matrix = _unit_like_matrix()

    class _PollMatrix(_FakeMatrix):
        async def get_input_names(self):
            return {i: f"In {i}" for i in range(1, 9)}

        async def get_output_names(self):
            return {i: f"Out {i}" for i in range(1, 9)}

        async def get_routing_state(self):
            return {i: i for i in range(1, 9)}

    pm = _PollMatrix(matrix.sys_names, matrix.user_names)
    mqtt = _FakeMqtt()
    poller = Poller(matrix=pm, mqtt=mqtt, settings=_Settings(), edid_catalogue=EdidCatalogue())
    await poller.poll_once()

    for topic, _payload, retain in mqtt.published:
        if topic.startswith("matrix/edid/"):
            assert retain is False


@pytest.mark.asyncio
async def test_catalogue_never_offers_a_slot_the_writer_would_reject():
    """A slot that reads fine but sits above the write-side ceiling is not an
    option — `set_input_edid` would raise ValueError on it."""
    over = dict.fromkeys(range(1, 15), "HDMI Matrix")
    matrix = _FakeMatrix(over, {})
    cat = EdidCatalogue()
    await cat.ensure_loaded(matrix)
    sys_indexes = [o.index for o in cat.options if o.source == "sys"]
    assert sys_indexes == list(range(1, 11))
