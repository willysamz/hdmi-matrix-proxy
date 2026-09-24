"""Tests for per-input EDID control.

Covers four layers:
- `MatrixClient` — exact command strings, the `,0` all-inputs form, range
  validation before any HTTP call, the `OK` body check, `ERROR` meaning
  "absent slot" while a transport or parse failure raises, and the port reset.
- `EdidCatalogue` — a bounded probe with code-owned option strings.
- The HA surface — discovery payloads and the controller's command handler.
- The REST surface lives in `tests/test_edid_api.py`.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.controller import Controller, ControllerError
from app.discovery import input_edid_select_payload, input_resolution_sensor_payload
from app.edid import EdidCatalogue, EdidOption, probe_catalogue
from app.matrix_client import MatrixClient

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

SYS8 = "SYS 8 · UHD4K60"
SYS7 = "SYS 7 · UHD4K30"
USER1 = "USER 1"


def _ok_response():
    resp = AsyncMock()
    resp.status_code = 200
    resp.text = "OK"
    resp.raise_for_status = MagicMock()
    return resp


def _mock_http(post_side_effect=None, post_return=None):
    """Build a mocked httpx.AsyncClient the way the existing tests do."""
    generic = _ok_response()
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
        _args, kwargs = call
        data = kwargs.get("data") or {}
        if "cmd" in data:
            out.append(data["cmd"])
    return out


# --------------------------------------------------------------------------
# MatrixClient.set_input_edid — command shape
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "index", "input_num", "expected"),
    [
        ("sys", 8, 6, "@EDID-SW-SYS:8,6"),
        ("user", 1, 6, "@EDID-SW-USER:1,6"),
        ("out", 3, 2, "@EDID-SW-OUT:3,2"),
        ("sys", 10, 1, "@EDID-SW-SYS:10,1"),
    ],
)
@pytest.mark.asyncio
async def test_set_input_edid_builds_documented_command(source, index, input_num, expected):
    """Raw, unpadded index and input — unlike @PORT-RESET, which pads."""
    http = _mock_http()
    client = await _started_client(http)
    try:
        assert await client.set_input_edid(source, index, input_num, rehandshake=False) is True
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
        # And no port reset: that would reset all eight ports at once.
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
        ("sys", 1, 9),
        ("sys", 1, -1),
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
async def test_set_input_edid_rejects_input_zero_explicitly():
    """0 is the device's all-inputs sentinel. `None` is the only way to mean
    that; a 0 arriving from a topic segment or a JSON body is a mistake."""
    http = _mock_http()
    client = await _started_client(http)
    try:
        http.post.reset_mock()
        with pytest.raises(ValueError):
            await client.set_input_edid("sys", 8, 0)
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


@pytest.mark.asyncio
async def test_set_input_edid_returns_false_when_the_device_does_not_say_ok():
    """An unacknowledged command must not look applied — that is exactly how
    the multiviewer's HDCP select accepted `Off` and kept its old value."""
    http = _mock_http(post_return=_response("ERROR"))
    client = await _started_client(http)
    try:
        assert await client.set_input_edid("sys", 8, 6) is False
        # And no re-handshake for a command that was refused.
        assert _commands(http) == ["@EDID-SW-SYS:8,6"]
    finally:
        await client.stop()


# --------------------------------------------------------------------------
# The re-handshake — an UNVERIFIED mechanism, kept structurally optional
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_input_edid_resets_the_input_port_by_default():
    """The proxy owns the re-handshake: it is the only layer that knows an
    EDID just changed and on which input."""
    http = _mock_http()
    client = await _started_client(http)
    try:
        await client.set_input_edid("sys", 8, 6)
        assert _commands(http) == ["@EDID-SW-SYS:8,6", "@PORT-RESET:0,06"]
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_set_input_edid_rehandshake_can_be_turned_off():
    """It is not verified that a re-handshake is needed at all, so it has to
    be switchable in one place."""
    http = _mock_http()
    client = await _started_client(http)
    try:
        await client.set_input_edid("sys", 8, 6, rehandshake=False)
        assert _commands(http) == ["@EDID-SW-SYS:8,6"]
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_reset_input_port_zero_pads_the_port():
    """Matches `uport()` in the unit's own api.js. @EDID-SW-* does NOT pad."""
    http = _mock_http()
    client = await _started_client(http)
    try:
        await client.reset_input_port(6)
        await client.reset_input_port(8)
        assert _commands(http) == ["@PORT-RESET:0,06", "@PORT-RESET:0,08"]
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_reset_input_port_validates_before_sending():
    http = _mock_http()
    client = await _started_client(http)
    try:
        http.post.reset_mock()
        with pytest.raises(ValueError):
            await client.reset_input_port(0)
        with pytest.raises(ValueError):
            await client.reset_input_port(9)
        assert http.post.call_count == 0
    finally:
        await client.stop()


# --------------------------------------------------------------------------
# MatrixClient.read_edid — absent vs failed
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_edid_returns_name_and_hex():
    resp = _response(
        '{"edid_name":"HDMI Matrix  ","edid_hex":"00FFFF"}',
        {"edid_name": "HDMI Matrix  ", "edid_hex": "00FFFF"},
    )
    http = _mock_http(post_return=resp)
    client = await _started_client(http)
    try:
        result = await client.read_edid("sys", 1)
        # Stripped: the device pads its names with trailing spaces.
        assert result == {"name": "HDMI Matrix", "hex": "00FFFF"}
        http.post.assert_called_with(
            "http://test-matrix.local/form-system-info.cgi",
            data={"sys_edid": "1"},
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
async def test_read_edid_error_body_means_absent_not_an_exception():
    """`out_edid` errors on this unit as a matter of course — never raise."""
    http = _mock_http(post_return=_response("ERROR"))
    client = await _started_client(http)
    try:
        assert await client.read_edid("out", 1) is None
        assert await client.read_edid("sys", 11) is None
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_read_edid_incomplete_payload_means_absent():
    """Index 0 answers with valid JSON and an empty name; both fields are
    required before a slot counts as present."""
    resp = _response('{"edid_name":"","edid_hex":""}', {"edid_name": "", "edid_hex": ""})
    http = _mock_http(post_return=resp)
    client = await _started_client(http)
    try:
        assert await client.read_edid("sys", 1) is None
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_read_edid_unparseable_body_raises_rather_than_looking_absent():
    """An unknown parameter comes back as a 4-byte non-JSON body. Treating
    that as 'absent' would silently truncate the catalogue."""
    http = _mock_http(post_return=_response("h' m"))
    client = await _started_client(http)
    try:
        with pytest.raises(RuntimeError):
            await client.read_edid("sys", 1)
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_read_edid_transport_failure_raises():
    """A timeout is not an ERROR. One dropped packet at slot 8 must not drop
    SYS 8 - UHD4K60, the exact EDID this feature exists to select."""
    http = _mock_http(post_side_effect=httpx.ConnectError("boom"))
    client = await _started_client(http)
    try:
        with pytest.raises(RuntimeError):
            await client.read_edid("sys", 8)
    finally:
        await client.stop()


# --------------------------------------------------------------------------
# get_input_info — the one genuine read-back
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_input_info_uses_a_zero_based_parameter():
    """`in_info` is 0-based, unlike every EDID parameter."""
    resp = _response(
        "{}",
        {"in_info": {"InputResolution": "3840x2160P60", "Hpd": "ON", "BoardType": "HDMI20"}},
    )
    http = _mock_http(post_return=resp)
    client = await _started_client(http)
    try:
        info = await client.get_input_info(6)
        assert info == {"resolution": "3840x2160P60", "hpd": "ON", "board_type": "HDMI20"}
        http.post.assert_called_with(
            "http://test-matrix.local/form-system-info.cgi",
            data={"in_info": "5"},
        )
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_get_input_info_returns_none_on_error():
    http = _mock_http(post_return=_response("ERROR"))
    client = await _started_client(http)
    try:
        assert await client.get_input_info(1) is None
    finally:
        await client.stop()


# --------------------------------------------------------------------------
# The catalogue
# --------------------------------------------------------------------------


class _FakeMatrix:
    """Reads that mirror the measured unit: SYS 1..10 and USER 1..5 present."""

    def __init__(self, sys_names: dict[int, str], user_names: dict[int, str]):
        self.sys_names = sys_names
        self.user_names = user_names
        self.reads: list[tuple[str, int]] = []
        self.writes: list[tuple[str, int, int | None]] = []
        self.rehandshakes: list[bool] = []
        self.fail_at: set[tuple[str, int]] = set()
        self.refuse = False

    async def read_edid(self, source, index):
        self.reads.append((source, index))
        if (source, index) in self.fail_at:
            raise RuntimeError("boom")
        table = self.sys_names if source == "sys" else self.user_names
        if index not in table:
            return None
        return {"name": table[index].strip(), "hex": f"{source}{index}hex"}

    async def set_input_edid(self, source, index, input_num, rehandshake=True):
        self.writes.append((source, index, input_num))
        self.rehandshakes.append(rehandshake)
        return not self.refuse

    async def get_input_names(self):
        return {i: f"In {i}" for i in range(1, 9)}

    async def get_output_names(self):
        return {i: f"Out {i}" for i in range(1, 9)}

    async def get_routing_state(self):
        return {i: i for i in range(1, 9)}

    async def get_input_info(self, input_num):
        return {"resolution": "1920x1080P60", "hpd": "ON", "board_type": "HDMI20"}


def _unit_like_matrix() -> _FakeMatrix:
    # Names as the device actually reports them: padded, repeated, ambiguous.
    sys_names = dict.fromkeys(range(1, 7), "HDMI Matrix  ")
    sys_names[7] = "UHD4K30"
    sys_names[8] = "UHD4K60"
    sys_names[9] = "UHD8K60"
    sys_names[10] = "UHD8K60"
    user_names = dict.fromkeys(range(1, 3), "Beyond TV")
    user_names.update(dict.fromkeys(range(3, 6), "HDMI Matrix  "))
    return _FakeMatrix(sys_names, user_names)


@pytest.mark.asyncio
async def test_catalogue_probes_a_bounded_range_not_until_the_first_error():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    assert await cat.build(matrix) is True

    sys_reads = [i for src, i in matrix.reads if src == "sys"]
    user_reads = [i for src, i in matrix.reads if src == "user"]
    # Every slot in range is visited; a gap does not stop the walk.
    assert sys_reads == list(range(1, 11))
    assert user_reads == list(range(1, 6))
    assert [o.index for o in cat.options if o.source == "sys"] == list(range(1, 11))
    assert [o.index for o in cat.options if o.source == "user"] == list(range(1, 6))


@pytest.mark.asyncio
async def test_catalogue_does_not_stop_at_a_gap():
    """An absent slot in the middle is skipped, not treated as the end."""
    matrix = _FakeMatrix({1: "a", 2: "b", 4: "d"}, {1: "u"})
    cat = EdidCatalogue()
    await cat.build(matrix)
    assert [o.index for o in cat.options if o.source == "sys"] == [1, 2, 4]


@pytest.mark.asyncio
async def test_catalogue_abandons_the_build_on_a_transport_failure():
    """A truncated catalogue is worse than none — it looks complete."""
    matrix = _unit_like_matrix()
    matrix.fail_at = {("sys", 8)}
    cat = EdidCatalogue()
    assert await cat.build(matrix) is False
    assert cat.loaded is False
    assert cat.options == []


@pytest.mark.asyncio
async def test_catalogue_retries_a_failed_read_once():
    class _FlakyOnce(_FakeMatrix):
        def __init__(self, *a):
            super().__init__(*a)
            self.failed = False

        async def read_edid(self, source, index):
            if (source, index) == ("sys", 8) and not self.failed:
                self.failed = True
                raise RuntimeError("one dropped packet")
            return await super().read_edid(source, index)

    base = _unit_like_matrix()
    matrix = _FlakyOnce(base.sys_names, base.user_names)
    cat = EdidCatalogue()
    assert await cat.build(matrix) is True
    assert SYS8 in cat.labels


@pytest.mark.asyncio
async def test_catalogue_never_offers_a_slot_the_writer_would_reject():
    matrix = _FakeMatrix(dict.fromkeys(range(1, 15), "HDMI Matrix"), {})
    cat = EdidCatalogue()
    await cat.build(matrix)
    assert [o.index for o in cat.options if o.source == "sys"] == list(range(1, 11))


@pytest.mark.asyncio
async def test_option_labels_are_code_owned_not_the_device_name():
    """Six slots report 'HDMI Matrix  ' with trailing spaces and differing
    content; an option built from that would be ambiguous, and it would churn
    the moment somebody writes a user slot."""
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.build(matrix)

    labels = cat.labels
    assert SYS8 in labels
    assert SYS7 in labels
    assert USER1 in labels
    assert "SYS 1 · HD8Stereo" in labels
    assert not any("HDMI Matrix" in label for label in labels)
    assert not any("Beyond TV" in label for label in labels)
    assert all(label == label.strip() for label in labels)
    assert len(labels) == len(set(labels))


@pytest.mark.asyncio
async def test_catalogue_keeps_the_device_name_for_diagnostics_only():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.build(matrix)
    sys1 = next(o for o in cat.options if o.source == "sys" and o.index == 1)
    assert sys1.device_name == "HDMI Matrix"
    assert sys1.device_name not in sys1.label


@pytest.mark.asyncio
async def test_catalogue_offers_no_copy_from_output_options():
    """`@EDID-SW-OUT` copies whatever the attached TV advertises — from the
    Theater TV that is how the HDR/DV metadata would come straight back."""
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.build(matrix)
    assert all(o.source != "out" for o in cat.options)
    assert not any("output" in label.lower() for label in cat.labels)


@pytest.mark.asyncio
async def test_catalogue_is_cached_and_not_reprobed():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.build(matrix)
    first = len(matrix.reads)
    await cat.build(matrix)
    assert len(matrix.reads) == first


@pytest.mark.asyncio
async def test_catalogue_resolves_a_label_back_to_a_slot():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.build(matrix)
    option = cat.resolve(SYS8)
    assert option is not None
    assert (option.source, option.index) == ("sys", 8)
    assert cat.resolve("nope") is None


@pytest.mark.asyncio
async def test_probe_returns_nothing_when_no_slot_reads():
    class _Dead:
        async def read_edid(self, source, index):
            return None

    assert await probe_catalogue(_Dead()) == []
    cat = EdidCatalogue()
    assert await cat.build(_Dead()) is False
    assert cat.loaded is False  # retried on the next poll cycle


def test_option_label_falls_back_when_the_index_has_no_known_name():
    assert EdidOption(source="sys", index=99).label == "SYS 99"
    assert EdidOption(source="user", index=3).label == "USER 3"


# --------------------------------------------------------------------------
# Discovery payloads
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
        options=[SYS8],
    )
    assert topic == "homeassistant/select/hdmi_matrix_input_6_edid/config"
    assert payload["object_id"] == "hdmi_matrix_input_6_edid"
    assert payload["unique_id"] == "hdmi_matrix_input_6_edid"
    assert payload["options"] == [SYS8]
    assert payload["command_topic"] == "matrix/edid/input/6/set"
    # REVISED 2026-09-24. This used to require "not read back" IN THE NAME. It was
    # there for a good reason — the assignment genuinely cannot be read from the
    # device — but Home Assistant derives a new entity's entity_id from the device
    # name plus this name, IGNORING object_id, so the warning became part of the id:
    #   select.home_lab_hdmi_matrix_playstation_5_edid_set_not_read_back
    # which is what every scene and automation would have to reference. The warning
    # now lives in the docs and the app card; the name stays addressable.
    assert payload["name"] == "PlayStation 5 EDID"
    assert "not read back" not in payload["name"].lower()


def test_input_resolution_sensor_discovery_payload():
    topic, payload = input_resolution_sensor_payload(
        discovery_prefix="homeassistant",
        device_id="hdmi_matrix",
        device_name="HDMI Matrix",
        state_topic="matrix/edid/input/6/resolution",
        availability_topic="matrix/bridge/available",
        input_number=6,
        input_name="PlayStation 5",
    )
    assert topic == "homeassistant/sensor/hdmi_matrix_input_6_resolution/config"
    assert payload["object_id"] == "hdmi_matrix_input_6_resolution"
    assert "command_topic" not in payload


# --------------------------------------------------------------------------
# Controller
# --------------------------------------------------------------------------


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
    matrix_edid_rehandshake = True
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


async def _loaded_controller():
    matrix = _unit_like_matrix()
    cat = EdidCatalogue()
    await cat.build(matrix)
    return (matrix, *_controller(matrix, cat))


@pytest.mark.asyncio
async def test_controller_sets_edid_and_echoes_what_it_set():
    matrix, c, mqtt, poller = await _loaded_controller()

    await c.set_input_edid(6, SYS8)

    assert matrix.writes == [("sys", 8, 6)]
    # Retained: nothing is published at boot, so the broker replays this.
    assert ("matrix/edid/input/6/state", SYS8, True) in mqtt.published
    # There is nothing to poll for EDID — the poller reads routing only.
    assert poller.polled is False


@pytest.mark.asyncio
async def test_controller_publishes_nothing_when_the_device_refuses():
    matrix, c, mqtt, _ = await _loaded_controller()
    matrix.refuse = True

    with pytest.raises(ControllerError):
        await c.set_input_edid(6, SYS8)
    assert mqtt.published == []


@pytest.mark.asyncio
async def test_controller_rejects_an_option_not_in_the_catalogue():
    matrix, c, mqtt, _ = await _loaded_controller()

    with pytest.raises(ControllerError):
        await c.set_input_edid(6, "SYS 99 · Nope")
    assert matrix.writes == []
    assert mqtt.published == []


@pytest.mark.asyncio
async def test_controller_rejects_input_zero_and_out_of_range():
    matrix, c, _, _ = await _loaded_controller()

    for bad in (0, 9, -1):
        with pytest.raises(ControllerError):
            await c.set_input_edid(bad, SYS8)
    assert matrix.writes == []


@pytest.mark.asyncio
async def test_controller_refuses_before_the_catalogue_is_built():
    matrix = _unit_like_matrix()
    c, _, _ = _controller(matrix, EdidCatalogue())
    with pytest.raises(ControllerError):
        await c.set_input_edid(6, SYS8)
    assert matrix.writes == []
    # And it does not build the catalogue itself — that is the poller's job,
    # off the boot path.
    assert matrix.reads == []


@pytest.mark.asyncio
async def test_controller_passes_the_rehandshake_setting_through():
    matrix, c, _, _ = await _loaded_controller()
    await c.set_input_edid(6, SYS8)
    assert matrix.rehandshakes == [True]

    matrix2, c2, _, _ = await _loaded_controller()
    c2.settings.matrix_edid_rehandshake = False
    await c2.set_input_edid(6, SYS8)
    assert matrix2.rehandshakes == [False]


@pytest.mark.asyncio
async def test_redundant_set_does_not_touch_the_device():
    """Scenes set the EDID explicitly AND an automation watches the selects,
    so the same value arrives twice on purpose. The second must not
    re-handshake — that would blink the very source we are protecting."""
    matrix, c, mqtt, _ = await _loaded_controller()

    await c.set_input_edid(6, SYS8)
    await c.set_input_edid(6, SYS8)

    assert matrix.writes == [("sys", 8, 6)]
    states = [p for t, p, _ in mqtt.published if t == "matrix/edid/input/6/state"]
    assert states == [SYS8, SYS8]


@pytest.mark.asyncio
async def test_a_refused_set_is_not_remembered_as_applied():
    matrix, c, _, _ = await _loaded_controller()
    matrix.refuse = True
    with pytest.raises(ControllerError):
        await c.set_input_edid(6, SYS8)
    matrix.refuse = False
    await c.set_input_edid(6, SYS8)
    assert matrix.writes == [("sys", 8, 6), ("sys", 8, 6)]


@pytest.mark.asyncio
async def test_a_different_value_still_writes():
    matrix, c, _, _ = await _loaded_controller()
    await c.set_input_edid(6, SYS8)
    await c.set_input_edid(6, SYS7)
    assert matrix.writes == [("sys", 8, 6), ("sys", 7, 6)]


@pytest.mark.asyncio
async def test_dedupe_is_per_input():
    matrix, c, _, _ = await _loaded_controller()
    await c.set_input_edid(6, SYS8)
    await c.set_input_edid(5, SYS8)
    assert matrix.writes == [("sys", 8, 6), ("sys", 8, 5)]


# --------------------------------------------------------------------------
# Poller
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poller_builds_the_catalogue_and_publishes_the_selects():
    from app.poller import Poller

    matrix = _unit_like_matrix()
    mqtt = _FakeMqtt()
    cat = EdidCatalogue()
    poller = Poller(matrix=matrix, mqtt=mqtt, settings=_Settings(), edid_catalogue=cat)
    await poller.poll_once()

    assert cat.loaded is True
    topics = [t for t, _, _ in mqtt.published]
    assert "homeassistant/select/hdmi_matrix_input_6_edid/config" in topics
    assert "homeassistant/sensor/hdmi_matrix_input_6_resolution/config" in topics


@pytest.mark.asyncio
async def test_poller_publishes_no_edid_state_at_boot():
    """Retained state plus nothing published at boot: the broker replays the
    last value. The alternative (publish unknown, never retain) is the other
    valid choice — but not both."""
    from app.poller import Poller

    matrix = _unit_like_matrix()
    mqtt = _FakeMqtt()
    poller = Poller(matrix=matrix, mqtt=mqtt, settings=_Settings(), edid_catalogue=EdidCatalogue())
    await poller.poll_once()

    assert not [t for t, _, _ in mqtt.published if t.endswith("/edid/input/6/state")]


@pytest.mark.asyncio
async def test_poller_publishes_input_resolution_on_delta():
    from app.poller import Poller

    matrix = _unit_like_matrix()
    mqtt = _FakeMqtt()
    poller = Poller(matrix=matrix, mqtt=mqtt, settings=_Settings(), edid_catalogue=EdidCatalogue())

    # Resolutions publish on EVERY OTHER cycle (2026-09-24): eight extra POSTs on
    # top of the three a cycle already makes would be ~3.7x the device's traffic,
    # and the matrix is the constraint, not our HTTP client. So cycle 1 is silent.
    await poller.poll_once()
    assert not [t for t, _, _ in mqtt.published if t.endswith("/resolution")], (
        "cycle 1 must not hit the device for resolutions"
    )

    await poller.poll_once()
    first = [(t, p) for t, p, _ in mqtt.published if t == "matrix/edid/input/6/resolution"]
    assert first == [("matrix/edid/input/6/resolution", "1920x1080P60")]

    # cycle 3 silent again (throttle), cycle 4 would publish but the value is
    # unchanged, so the delta check keeps it quiet too
    mqtt.published.clear()
    await poller.poll_once()
    await poller.poll_once()
    assert not [t for t, _, _ in mqtt.published if t.endswith("/resolution")]


@pytest.mark.asyncio
async def test_poller_retries_the_catalogue_when_the_probe_failed():
    from app.poller import Poller

    matrix = _unit_like_matrix()
    matrix.fail_at = {("sys", 8)}
    mqtt = _FakeMqtt()
    cat = EdidCatalogue()
    poller = Poller(matrix=matrix, mqtt=mqtt, settings=_Settings(), edid_catalogue=cat)

    await poller.poll_once()
    assert cat.loaded is False
    # No select published with an empty option list.
    assert not [t for t, _, _ in mqtt.published if "select/hdmi_matrix_input_6_edid" in t]

    matrix.fail_at = set()
    await poller.poll_once()
    assert cat.loaded is True
    assert [t for t, _, _ in mqtt.published if "select/hdmi_matrix_input_6_edid" in t]


@pytest.mark.asyncio
async def test_set_routing_returns_false_when_the_device_does_not_say_ok():
    """Regression, fixed 2026-09-24. `set_routing` used to discard the response
    body and return True unconditionally, so a routing command the device
    REFUSED still reported success. Same defect the EDID path was written to
    avoid; this pins the fix on the older path too."""
    http = _mock_http()
    client = await _started_client(http)
    try:
        http.post.return_value = _response("ERROR")
        assert await client.set_routing(3, 1) is False
        http.post.return_value = _response("OK")
        assert await client.set_routing(3, 1) is True
    finally:
        await client.stop()
