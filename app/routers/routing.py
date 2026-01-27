"""Routing control endpoints."""

from fastapi import APIRouter, Body, HTTPException, Path, status

from app.dependencies import get_matrix_client
from app.models import (
    OutputRouting,
    PresetRoutingRequest,
    PresetRoutingResponse,
    RoutingState,
    SetRoutingRequest,
    SetRoutingResponse,
)

router = APIRouter()


@router.get(
    "/routing",
    response_model=RoutingState,
    summary="Get all routing state",
)
async def get_routing() -> RoutingState:
    """Get current input->output routing for all outputs.

    Includes custom input and output names from the matrix.

    Note: The matrix may not support querying routing state.
    This returns an empty state. Consider tracking state locally.

    Returns:
        Current routing state for all 8 outputs with custom names
    """
    client = get_matrix_client()
    state = await client.get_routing_state()

    # Fetch custom names from matrix
    input_names = await client.get_input_names()
    output_names = await client.get_output_names()

    outputs = []
    for output_num in range(1, 9):
        input_num = state.get(output_num)
        outputs.append(
            OutputRouting(
                output=output_num,
                output_name=output_names.get(output_num),
                input=input_num,
                input_name=input_names.get(input_num) if input_num else None,
            )
        )

    return RoutingState(outputs=outputs, input_names=input_names, output_names=output_names)


@router.get(
    "/routing/output/{output_id}",
    response_model=OutputRouting,
    summary="Get routing for specific output",
)
async def get_output_routing(
    output_id: int = Path(ge=1, le=8, description="Output number (1-8)"),
) -> OutputRouting:
    """Get current input routed to a specific output.

    Includes custom input and output names from the matrix.

    Args:
        output_id: Output number (1-8)

    Returns:
        Current input routed to this output with custom names
    """
    client = get_matrix_client()
    state = await client.get_routing_state()

    # Fetch custom names from matrix
    input_names = await client.get_input_names()
    output_names = await client.get_output_names()

    input_num = state.get(output_id)

    return OutputRouting(
        output=output_id,
        output_name=output_names.get(output_id),
        input=input_num,
        input_name=input_names.get(input_num) if input_num else None,
    )


@router.post(
    "/routing/output/{output_id}",
    response_model=SetRoutingResponse,
    summary="Set routing for specific output",
    status_code=status.HTTP_200_OK,
)
async def set_output_routing(
    output_id: int = Path(ge=1, le=8, description="Output number (1-8)"),
    request: SetRoutingRequest = Body(...),
) -> SetRoutingResponse:
    """Route an input to a specific output.

    Args:
        output_id: Output number (1-8)
        request: Input number to route (1-8)

    Returns:
        Success status and routing confirmation
    """
    client = get_matrix_client()

    try:
        await client.set_routing(input_num=request.input, output_num=output_id)

        return SetRoutingResponse(
            output=output_id,
            input=request.input,
            success=True,
            message=f"Routed input {request.input} to output {output_id}",
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Matrix communication error: {e}",
        ) from e


@router.post(
    "/routing/preset",
    response_model=PresetRoutingResponse,
    summary="Set multiple routings at once",
    status_code=status.HTTP_200_OK,
)
async def set_preset_routing(request: PresetRoutingRequest) -> PresetRoutingResponse:
    """Set multiple output routings at once.

    Args:
        request: Dictionary of output->input mappings

    Returns:
        Success status with applied and failed mappings
    """
    client = get_matrix_client()

    applied: dict[int, int] = {}
    failed: dict[int, str] = {}

    for output_num, input_num in request.mappings.items():
        if not 1 <= output_num <= 8:
            failed[output_num] = f"Invalid output number: {output_num}"
            continue

        if not 1 <= input_num <= 8:
            failed[output_num] = f"Invalid input number: {input_num}"
            continue

        try:
            await client.set_routing(input_num=input_num, output_num=output_num)
            applied[output_num] = input_num
        except Exception as e:
            failed[output_num] = str(e)

    success = len(failed) == 0

    return PresetRoutingResponse(
        success=success,
        applied=applied,
        failed=failed,
    )
