from __future__ import annotations as _annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Annotated, Any, Literal, Union, cast, overload

import pydantic
import pydantic_core

from ._utils import now_utc as _now_utc
from .exceptions import UnexpectedModelBehavior


@dataclass
class SystemPromptPart:
    """A system prompt, generally written by the application developer.

    This gives the model context and guidance on how to respond.
    """

    content: str
    """The content of the prompt."""

    dynamic_ref: str | None = None
    """The ref of the dynamic system prompt function that generated this part.

    Only set if system prompt is dynamic, see [`system_prompt`][pydantic_ai.Agent.system_prompt] for more information.
    """

    part_kind: Literal['system-prompt'] = field(default='system-prompt', init=False, repr=False)
    """Part type identifier, this is available on all parts as a discriminator."""


@dataclass
class UserPromptPart:
    """A user prompt, generally written by the end user.

    Content comes from the `user_prompt` parameter of [`Agent.run`][pydantic_ai.Agent.run],
    [`Agent.run_sync`][pydantic_ai.Agent.run_sync], and [`Agent.run_stream`][pydantic_ai.Agent.run_stream].
    """

    content: str
    """The content of the prompt."""

    timestamp: datetime = field(default_factory=_now_utc)
    """The timestamp of the prompt."""

    part_kind: Literal['user-prompt'] = field(default='user-prompt', init=False, repr=False)
    """Part type identifier, this is available on all parts as a discriminator."""


tool_return_ta: pydantic.TypeAdapter[Any] = pydantic.TypeAdapter(Any, config=pydantic.ConfigDict(defer_build=True))


@dataclass
class ToolReturnPart:
    """A tool return message, this encodes the result of running a tool."""

    tool_name: str
    """The name of the "tool" was called."""

    content: Any
    """The return value."""

    tool_call_id: str | None = None
    """Optional tool call identifier, this is used by some models including OpenAI."""

    timestamp: datetime = field(default_factory=_now_utc)
    """The timestamp, when the tool returned."""

    part_kind: Literal['tool-return'] = field(default='tool-return', init=False, repr=False)
    """Part type identifier, this is available on all parts as a discriminator."""

    def model_response_str(self) -> str:
        """Return a string representation of the content for the model."""
        if isinstance(self.content, str):
            return self.content
        else:
            return tool_return_ta.dump_json(self.content).decode()

    def model_response_object(self) -> dict[str, Any]:
        """Return a dictionary representation of the content, wrapping non-dict types appropriately."""
        # gemini supports JSON dict return values, but no other JSON types, hence we wrap anything else in a dict
        if isinstance(self.content, dict):
            return tool_return_ta.dump_python(self.content, mode='json')  # pyright: ignore[reportUnknownMemberType]
        else:
            return {'return_value': tool_return_ta.dump_python(self.content, mode='json')}


error_details_ta = pydantic.TypeAdapter(list[pydantic_core.ErrorDetails], config=pydantic.ConfigDict(defer_build=True))


@dataclass
class RetryPromptPart:
    """A message back to a model asking it to try again.

    This can be sent for a number of reasons:

    * Pydantic validation of tool arguments failed, here content is derived from a Pydantic
      [`ValidationError`][pydantic_core.ValidationError]
    * a tool raised a [`ModelRetry`][pydantic_ai.exceptions.ModelRetry] exception
    * no tool was found for the tool name
    * the model returned plain text when a structured response was expected
    * Pydantic validation of a structured response failed, here content is derived from a Pydantic
      [`ValidationError`][pydantic_core.ValidationError]
    * a result validator raised a [`ModelRetry`][pydantic_ai.exceptions.ModelRetry] exception
    """

    content: list[pydantic_core.ErrorDetails] | str
    """Details of why and how the model should retry.

    If the retry was triggered by a [`ValidationError`][pydantic_core.ValidationError], this will be a list of
    error details.
    """

    tool_name: str | None = None
    """The name of the tool that was called, if any."""

    tool_call_id: str | None = None
    """Optional tool call identifier, this is used by some models including OpenAI."""

    timestamp: datetime = field(default_factory=_now_utc)
    """The timestamp, when the retry was triggered."""

    part_kind: Literal['retry-prompt'] = field(default='retry-prompt', init=False, repr=False)
    """Part type identifier, this is available on all parts as a discriminator."""

    def model_response(self) -> str:
        """Return a string message describing why the retry is requested."""
        if isinstance(self.content, str):
            description = self.content
        else:
            json_errors = error_details_ta.dump_json(self.content, exclude={'__all__': {'ctx'}}, indent=2)
            description = f'{len(self.content)} validation errors: {json_errors.decode()}'
        return f'{description}\n\nFix the errors and try again.'


ModelRequestPart = Annotated[
    Union[SystemPromptPart, UserPromptPart, ToolReturnPart, RetryPromptPart], pydantic.Discriminator('part_kind')
]
"""A message part sent by PydanticAI to a model."""


@dataclass
class ModelRequest:
    """A request generated by PydanticAI and sent to a model, e.g. a message from the PydanticAI app to the model."""

    parts: list[ModelRequestPart]
    """The parts of the user message."""

    kind: Literal['request'] = field(default='request', init=False, repr=False)
    """Message type identifier, this is available on all parts as a discriminator."""


@dataclass
class TextPart:
    """A plain text response from a model."""

    content: str
    """The text content of the response."""

    part_kind: Literal['text'] = field(default='text', init=False, repr=False)
    """Part type identifier, this is available on all parts as a discriminator."""

    def has_content(self) -> bool:
        """Return `True` if the text content is non-empty."""
        return bool(self.content)


@dataclass
class ToolCallPart:
    """A tool call from a model."""

    tool_name: str
    """The name of the tool to call."""

    args: str | dict[str, Any]
    """The arguments to pass to the tool.

    This is stored either as a JSON string or a Python dictionary depending on how data was received.
    """

    tool_call_id: str | None = None
    """Optional tool call identifier, this is used by some models including OpenAI."""

    part_kind: Literal['tool-call'] = field(default='tool-call', init=False, repr=False)
    """Part type identifier, this is available on all parts as a discriminator."""

    def args_as_dict(self) -> dict[str, Any]:
        """Return the arguments as a Python dictionary.

        This is just for convenience with models that require dicts as input.
        """
        if isinstance(self.args, dict):
            return self.args
        args = pydantic_core.from_json(self.args)
        assert isinstance(args, dict), 'args should be a dict'
        return cast(dict[str, Any], args)

    def args_as_json_str(self) -> str:
        """Return the arguments as a JSON string.

        This is just for convenience with models that require JSON strings as input.
        """
        if isinstance(self.args, str):
            return self.args
        return pydantic_core.to_json(self.args).decode()

    def has_content(self) -> bool:
        """Return `True` if the arguments contain any data."""
        if isinstance(self.args, dict):
            # TODO: This should probably return True if you have the value False, or 0, etc.
            #   It makes sense to me to ignore empty strings, but not sure about empty lists or dicts
            return any(self.args.values())
        else:
            return bool(self.args)


ModelResponsePart = Annotated[Union[TextPart, ToolCallPart], pydantic.Discriminator('part_kind')]
"""A message part returned by a model."""


@dataclass
class ModelResponse:
    """A response from a model, e.g. a message from the model to the PydanticAI app."""

    parts: list[ModelResponsePart]
    """The parts of the model message."""

    model_name: str | None = None
    """The name of the model that generated the response."""

    timestamp: datetime = field(default_factory=_now_utc)
    """The timestamp of the response.

    If the model provides a timestamp in the response (as OpenAI does) that will be used.
    """

    kind: Literal['response'] = field(default='response', init=False, repr=False)
    """Message type identifier, this is available on all parts as a discriminator."""


ModelMessage = Annotated[Union[ModelRequest, ModelResponse], pydantic.Discriminator('kind')]
"""Any message sent to or returned by a model."""

ModelMessagesTypeAdapter = pydantic.TypeAdapter(list[ModelMessage], config=pydantic.ConfigDict(defer_build=True))
"""Pydantic [`TypeAdapter`][pydantic.type_adapter.TypeAdapter] for (de)serializing messages."""


@dataclass
class TextPartDelta:
    """A partial update (delta) for a `TextPart` to append new text content."""

    content_delta: str
    """The incremental text content to add to the existing `TextPart` content."""

    part_delta_kind: Literal['text'] = field(default='text', init=False, repr=False)
    """Part delta type identifier, used as a discriminator."""

    def apply(self, part: ModelResponsePart) -> TextPart:
        """Apply this text delta to an existing `TextPart`.

        Args:
            part: The existing model response part, which must be a `TextPart`.

        Returns:
            A new `TextPart` with updated text content.

        Raises:
            ValueError: If `part` is not a `TextPart`.
        """
        if not isinstance(part, TextPart):
            raise ValueError('Cannot apply TextPartDeltas to non-TextParts')
        return replace(part, content=part.content + self.content_delta)


@dataclass
class ToolCallPartDelta:
    """A partial update (delta) for a `ToolCallPart` to modify tool name, arguments, or tool call ID."""

    tool_name_delta: str | None = None
    """Incremental text to add to the existing tool name, if any."""

    args_delta: str | dict[str, Any] | None = None
    """Incremental data to add to the tool arguments.

    If this is a string, it will be appended to existing JSON arguments.
    If this is a dict, it will be merged with existing dict arguments.
    """

    tool_call_id: str | None = None
    """Optional tool call identifier, this is used by some models including OpenAI.

    Note this is never treated as a delta — it can replace None, but otherwise if a
    non-matching value is provided an error will be raised."""

    part_delta_kind: Literal['tool_call'] = field(default='tool_call', init=False, repr=False)
    """Part delta type identifier, used as a discriminator."""

    def as_part(self) -> ToolCallPart | None:
        """Convert this delta to a fully formed `ToolCallPart` if possible, otherwise return `None`.

        Returns:
            A `ToolCallPart` if both `tool_name_delta` and `args_delta` are set, otherwise `None`.
        """
        if self.tool_name_delta is None or self.args_delta is None:
            return None

        return ToolCallPart(
            self.tool_name_delta,
            self.args_delta,
            self.tool_call_id,
        )

    @overload
    def apply(self, part: ModelResponsePart) -> ToolCallPart: ...

    @overload
    def apply(self, part: ModelResponsePart | ToolCallPartDelta) -> ToolCallPart | ToolCallPartDelta: ...

    def apply(self, part: ModelResponsePart | ToolCallPartDelta) -> ToolCallPart | ToolCallPartDelta:
        """Apply this delta to a part or delta, returning a new part or delta with the changes applied.

        Args:
            part: The existing model response part or delta to update.

        Returns:
            Either a new `ToolCallPart` or an updated `ToolCallPartDelta`.

        Raises:
            ValueError: If `part` is neither a `ToolCallPart` nor a `ToolCallPartDelta`.
            UnexpectedModelBehavior: If applying JSON deltas to dict arguments or vice versa.
        """
        if isinstance(part, ToolCallPart):
            return self._apply_to_part(part)

        if isinstance(part, ToolCallPartDelta):
            return self._apply_to_delta(part)

        raise ValueError(f'Can only apply ToolCallPartDeltas to ToolCallParts or ToolCallPartDeltas, not {part}')

    def _apply_to_delta(self, delta: ToolCallPartDelta) -> ToolCallPart | ToolCallPartDelta:
        """Internal helper to apply this delta to another delta."""
        if self.tool_name_delta:
            # Append incremental text to the existing tool_name_delta
            updated_tool_name_delta = (delta.tool_name_delta or '') + self.tool_name_delta
            delta = replace(delta, tool_name_delta=updated_tool_name_delta)

        if isinstance(self.args_delta, str):
            if isinstance(delta.args_delta, dict):
                raise UnexpectedModelBehavior(
                    f'Cannot apply JSON deltas to non-JSON tool arguments ({delta=}, {self=})'
                )
            updated_args_delta = (delta.args_delta or '') + self.args_delta
            delta = replace(delta, args_delta=updated_args_delta)
        elif isinstance(self.args_delta, dict):
            if isinstance(delta.args_delta, str):
                raise UnexpectedModelBehavior(
                    f'Cannot apply dict deltas to non-dict tool arguments ({delta=}, {self=})'
                )
            updated_args_delta = {**(delta.args_delta or {}), **self.args_delta}
            delta = replace(delta, args_delta=updated_args_delta)

        if self.tool_call_id:
            # Set the tool_call_id if it wasn't present, otherwise error if it has changed
            if delta.tool_call_id is not None and delta.tool_call_id != self.tool_call_id:
                raise UnexpectedModelBehavior(
                    f'Cannot apply a new tool_call_id to a ToolCallPartDelta that already has one ({delta=}, {self=})'
                )
            delta = replace(delta, tool_call_id=self.tool_call_id)

        # If we now have enough data to create a full ToolCallPart, do so
        if delta.tool_name_delta is not None and delta.args_delta is not None:
            return ToolCallPart(
                delta.tool_name_delta,
                delta.args_delta,
                delta.tool_call_id,
            )

        return delta

    def _apply_to_part(self, part: ToolCallPart) -> ToolCallPart:
        """Internal helper to apply this delta directly to a `ToolCallPart`."""
        if self.tool_name_delta:
            # Append incremental text to the existing tool_name
            tool_name = part.tool_name + self.tool_name_delta
            part = replace(part, tool_name=tool_name)

        if isinstance(self.args_delta, str):
            if not isinstance(part.args, str):
                raise UnexpectedModelBehavior(f'Cannot apply JSON deltas to non-JSON tool arguments ({part=}, {self=})')
            updated_json = part.args + self.args_delta
            part = replace(part, args=updated_json)
        elif isinstance(self.args_delta, dict):
            if not isinstance(part.args, dict):
                raise UnexpectedModelBehavior(f'Cannot apply dict deltas to non-dict tool arguments ({part=}, {self=})')
            updated_dict = {**(part.args or {}), **self.args_delta}
            part = replace(part, args=updated_dict)

        if self.tool_call_id:
            # Replace the tool_call_id entirely if given
            if part.tool_call_id is not None and part.tool_call_id != self.tool_call_id:
                raise UnexpectedModelBehavior(
                    f'Cannot apply a new tool_call_id to a ToolCallPartDelta that already has one ({part=}, {self=})'
                )
            part = replace(part, tool_call_id=self.tool_call_id)
        return part


ModelResponsePartDelta = Annotated[Union[TextPartDelta, ToolCallPartDelta], pydantic.Discriminator('part_delta_kind')]
"""A partial update (delta) for any model response part."""


@dataclass
class PartStartEvent:
    """An event indicating that a new part has started.

    If multiple `PartStartEvent`s are received with the same index,
    the new one should fully replace the old one.
    """

    index: int
    """The index of the part within the overall response parts list."""

    part: ModelResponsePart
    """The newly started `ModelResponsePart`."""

    event_kind: Literal['part_start'] = field(default='part_start', init=False, repr=False)
    """Event type identifier, used as a discriminator."""


@dataclass
class PartDeltaEvent:
    """An event indicating a delta update for an existing part."""

    index: int
    """The index of the part within the overall response parts list."""

    delta: ModelResponsePartDelta
    """The delta to apply to the specified part."""

    event_kind: Literal['part_delta'] = field(default='part_delta', init=False, repr=False)
    """Event type identifier, used as a discriminator."""


ModelResponseStreamEvent = Annotated[Union[PartStartEvent, PartDeltaEvent], pydantic.Discriminator('event_kind')]
"""An event in the model response stream, either starting a new part or applying a delta to an existing one."""


@dataclass
class FunctionToolCallEvent:
    """An event indicating the start to a call to a function tool."""

    part: ToolCallPart
    """The (function) tool call to make."""
    call_id: str = field(init=False)
    """An ID used for matching details about the call to its result. If present, defaults to the part's tool_call_id."""
    event_kind: Literal['function_tool_call'] = field(default='function_tool_call', init=False, repr=False)
    """Event type identifier, used as a discriminator."""

    def __post_init__(self):
        self.call_id = self.part.tool_call_id or str(uuid.uuid4())


@dataclass
class FunctionToolResultEvent:
    """An event indicating the result of a function tool call."""

    result: ToolReturnPart | RetryPromptPart
    """The result of the call to the function tool."""
    call_id: str
    """An ID used to match the result to its original call."""
    event_kind: Literal['function_tool_result'] = field(default='function_tool_result', init=False, repr=False)
    """Event type identifier, used as a discriminator."""


HandleResponseEvent = Annotated[Union[FunctionToolCallEvent, FunctionToolResultEvent], pydantic.Discriminator('kind')]
