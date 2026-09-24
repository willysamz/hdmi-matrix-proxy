"""Per-input EDID endpoints.

The house's matrix scenes are REST: `script.ps5_gaming_preset` runs
`rest_command.matrix_preset`, and every matrix script and automation is a
`rest_command.matrix_*` against this proxy. An MQTT-only EDID surface would
leave them with no way to set one, so the capability is exposed both ways.
The operator's rule — Home Assistant talks to the proxy, never to the
device's CGI — is unaffected: this *is* the proxy.

**There is no GET for an input's current EDID, and there never can be.** The
matrix has no endpoint that reports the assignment. The nearest real signal is
the input's resolution, published as `sensor.<device>_input_N_resolution` on
the MQTT side and available here through the routing/system endpoints' device
info.
"""

from fastapi import APIRouter, Body, HTTPException, status

from app.dependencies import get_edid_catalogue, get_matrix_client
from app.models import (
    EdidCatalogueResponse,
    EdidOptionInfo,
    SetInputEdidRequest,
    SetInputEdidResponse,
)

router = APIRouter()


@router.get(
    "/edid",
    response_model=EdidCatalogueResponse,
    summary="List the EDID catalogue",
)
async def get_edid_catalogue_endpoint() -> EdidCatalogueResponse:
    """List the selectable EDIDs.

    Built by the MQTT poller on a cycle that reached the matrix. When MQTT is
    disabled nothing builds it, so this probes on demand — reads only, and
    never on the boot path.

    The `label` strings are code-owned constants, not the device's
    `edid_name`: on this unit six slots share one name and a user-slot write
    would change it, so labels sourced from the device would churn and break
    automations holding the old string.
    """
    catalogue = get_edid_catalogue()
    if not catalogue.loaded:
        await catalogue.build(get_matrix_client())

    options = [
        EdidOptionInfo(
            source=o.source,
            index=o.index,
            label=o.label,
            device_name=o.device_name,
        )
        for o in catalogue.options
    ]
    return EdidCatalogueResponse(
        loaded=catalogue.loaded,
        options=options,
        labels=[o.label for o in options],
    )


@router.post(
    "/edid",
    response_model=SetInputEdidResponse,
    summary="Assign an EDID to an input",
    status_code=status.HTTP_200_OK,
)
async def set_input_edid(
    request: SetInputEdidRequest = Body(...),
) -> SetInputEdidResponse:
    """Give one input a different EDID.

    ```json
    {"source": "sys", "index": 8, "input": 6}
    ```

    `input` is required and 1-8. The device's "all inputs" form (`,0`) is
    **not** reachable here: a misfired body should not retune every source in
    the house.

    By default the input port is reset afterwards (`@PORT-RESET:0,NN`) so the
    source re-reads the new EDID — a source only re-reads on a hotplug. That
    mechanism is **unverified**; see `MatrixClient.reset_input_port`. Pass
    `"rehandshake": false` to skip it.

    A response of `success: false` means the device refused the command. This
    unit answers plenty it then ignores, so the body is checked: it is not
    treated as applied unless the device said `OK`.
    """
    client = get_matrix_client()
    catalogue = get_edid_catalogue()

    try:
        ok = await client.set_input_edid(
            request.source,
            request.index,
            request.input,
            rehandshake=request.rehandshake,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Matrix communication error: {e}",
        ) from e

    input_names = await client.get_input_names()
    input_name = input_names.get(request.input)
    label = next(
        (
            o.label
            for o in catalogue.options
            if o.source == request.source and o.index == request.index
        ),
        None,
    )

    return SetInputEdidResponse(
        input=request.input,
        input_name=input_name,
        source=request.source,
        index=request.index,
        label=label,
        rehandshake=request.rehandshake,
        success=ok,
        message=(
            f"Assigned {label or f'{request.source.upper()} {request.index}'} "
            f"to {input_name or f'input {request.input}'}"
            if ok
            else "Matrix did not acknowledge the command with OK"
        ),
    )
