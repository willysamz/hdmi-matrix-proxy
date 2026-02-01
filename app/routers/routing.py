"""Routing control endpoints."""

from fastapi import APIRouter, Body, HTTPException, Path, status

from app.dependencies import get_matrix_client
from app.models import (
    InputInfo,
    InputListResponse,
    OutputInfo,
    OutputListResponse,
    OutputRouting,
    PresetRoutingRequest,
    PresetRoutingResponse,
    RoutingState,
    SetRoutingRequest,
    SetRoutingResponse,
)

router = APIRouter()


async def resolve_input_to_number(
    input_value: int | str, input_names: dict[int, str]
) -> int:
    """Resolve an input value (number or name) to an input number.

    Args:
        input_value: Input number (1-8) or input name string
        input_names: Dictionary mapping input numbers to names

    Returns:
        Input number (1-8)

    Raises:
        ValueError: If input name not found or number out of range
    """
    # If it's already an int, validate range
    if isinstance(input_value, int):
        if not 1 <= input_value <= 8:
            raise ValueError(f"Invalid input number: {input_value} (must be 1-8)")
        return input_value

    # It's a string - could be a number as string or a name
    # First try parsing as int
    try:
        num = int(input_value)
        if not 1 <= num <= 8:
            raise ValueError(f"Invalid input number: {num} (must be 1-8)")
        return num
    except ValueError:
        pass

    # It's a name - look it up (case-insensitive)
    input_value_lower = input_value.lower().strip()
    for num, name in input_names.items():
        if name.lower().strip() == input_value_lower:
            return num

    # Name not found - provide helpful error
    available = ", ".join(f'"{n}"' for n in input_names.values())
    raise ValueError(
        f'Input name "{input_value}" not found. Available inputs: {available}'
    )


async def resolve_output_to_number(
    output_value: int | str, output_names: dict[int, str]
) -> int:
    """Resolve an output value (number or name) to an output number.

    Args:
        output_value: Output number (1-8) or output name string
        output_names: Dictionary mapping output numbers to names

    Returns:
        Output number (1-8)

    Raises:
        ValueError: If output name not found or number out of range
    """
    # If it's already an int, validate range
    if isinstance(output_value, int):
        if not 1 <= output_value <= 8:
            raise ValueError(f"Invalid output number: {output_value} (must be 1-8)")
        return output_value

    # It's a string - could be a number as string or a name
    # First try parsing as int
    try:
        num = int(output_value)
        if not 1 <= num <= 8:
            raise ValueError(f"Invalid output number: {num} (must be 1-8)")
        return num
    except ValueError:
        pass

    # It's a name - look it up (case-insensitive)
    output_value_lower = output_value.lower().strip()
    for num, name in output_names.items():
        if name.lower().strip() == output_value_lower:
            return num

    # Name not found - provide helpful error
    available = ", ".join(f'"{n}"' for n in output_names.values())
    raise ValueError(
        f'Output name "{output_value}" not found. Available outputs: {available}'
    )


@router.get(
    "/inputs",
    response_model=InputListResponse,
    summary="Get all input names",
)
async def get_inputs() -> InputListResponse:
    """Get list of all inputs with their configured names.

    Use the `names` field for populating dropdown options in Home Assistant.

    Returns:
        List of inputs with numbers and names
    """
    client = get_matrix_client()
    input_names = await client.get_input_names()

    inputs = [
        InputInfo(number=num, name=input_names.get(num, f"HDMI {num}"))
        for num in range(1, 9)
    ]

    return InputListResponse(
        inputs=inputs,
        names=[i.name for i in inputs],
    )


@router.get(
    "/outputs",
    response_model=OutputListResponse,
    summary="Get all output names",
)
async def get_outputs() -> OutputListResponse:
    """Get list of all outputs with their configured names.

    Use the `names` field for populating dropdown options in Home Assistant.

    Returns:
        List of outputs with numbers and names
    """
    client = get_matrix_client()
    output_names = await client.get_output_names()

    outputs = [
        OutputInfo(number=num, name=output_names.get(num, f"Output {num}"))
        for num in range(1, 9)
    ]

    return OutputListResponse(
        outputs=outputs,
        names=[o.name for o in outputs],
    )


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
    output_id: str = Path(description="Output number (1-8) or output name"),
) -> OutputRouting:
    """Get current input routed to a specific output.

    The output can be specified as either:
    - A number (1-8): `/api/routing/output/1`
    - A name: `/api/routing/output/Living%20Room%20TV`

    Names are matched case-insensitively against the matrix's configured output names.

    Args:
        output_id: Output number (1-8) or output name

    Returns:
        Current input routed to this output with custom names
    """
    client = get_matrix_client()

    # Fetch custom names from matrix
    input_names = await client.get_input_names()
    output_names = await client.get_output_names()

    # Resolve output (could be number or name) to number
    try:
        output_num = await resolve_output_to_number(output_id, output_names)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    state = await client.get_routing_state()
    input_num = state.get(output_num)

    return OutputRouting(
        output=output_num,
        output_name=output_names.get(output_num),
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
    output_id: str = Path(description="Output number (1-8) or output name"),
    request: SetRoutingRequest = Body(...),
) -> SetRoutingResponse:
    """Route an input to a specific output.

    Both output and input can be specified by name or number:

    **By numbers:**
    - `POST /api/routing/output/1` with `{"input": 3}`

    **By names:**
    - `POST /api/routing/output/Living%20Room%20TV` with `{"input": "PlayStation 5"}`

    **Mixed:**
    - `POST /api/routing/output/1` with `{"input": "PlayStation 5"}`
    - `POST /api/routing/output/Living%20Room%20TV` with `{"input": 3}`

    Names are matched case-insensitively against the matrix's configured names.

    Args:
        output_id: Output number (1-8) or output name
        request: Input number (1-8) or input name to route

    Returns:
        Success status and routing confirmation with names
    """
    client = get_matrix_client()

    # Get names for resolution and response
    input_names = await client.get_input_names()
    output_names = await client.get_output_names()

    try:
        # Resolve output (could be number or name) to number
        output_num = await resolve_output_to_number(output_id, output_names)

        # Resolve input (could be number or name) to number
        input_num = await resolve_input_to_number(request.input, input_names)

        await client.set_routing(input_num=input_num, output_num=output_num)

        input_name = input_names.get(input_num, f"HDMI {input_num}")
        output_name = output_names.get(output_num, f"Output {output_num}")

        return SetRoutingResponse(
            output=output_num,
            output_name=output_name,
            input=input_num,
            input_name=input_name,
            success=True,
            message=f"Routed {input_name} to {output_name}",
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

    Both outputs and inputs can be specified by number or name:

    **By numbers:**
    ```json
    {"mappings": {"1": 3, "2": 4}}
    ```

    **By names:**
    ```json
    {"mappings": {"Living Room TV": "PlayStation 5", "Bedroom TV": "Apple TV"}}
    ```

    **Mixed:**
    ```json
    {"mappings": {"Living Room TV": "Apple TV", "2": 3, "3": "Xbox Series X"}}
    ```

    Names are matched case-insensitively against the matrix's configured names.

    Args:
        request: Dictionary of output->input mappings

    Returns:
        Success status with applied and failed mappings
    """
    client = get_matrix_client()

    # Get names for resolution
    input_names = await client.get_input_names()
    output_names = await client.get_output_names()

    applied: dict[int, int] = {}
    failed: dict[str, str] = {}

    for output_value, input_value in request.mappings.items():
        # Track the original key for error reporting
        output_key = str(output_value)

        try:
            # Resolve output (could be number or name) to number
            output_num = await resolve_output_to_number(output_value, output_names)

            # Resolve input (could be number or name) to number
            input_num = await resolve_input_to_number(input_value, input_names)

            await client.set_routing(input_num=input_num, output_num=output_num)
            applied[output_num] = input_num
        except ValueError as e:
            failed[output_key] = str(e)
        except Exception as e:
            failed[output_key] = str(e)

    success = len(failed) == 0

    return PresetRoutingResponse(
        success=success,
        applied=applied,
        failed=failed,
    )
