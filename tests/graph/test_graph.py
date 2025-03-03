# pyright: reportPrivateUsage=false
from __future__ import annotations as _annotations

from dataclasses import dataclass
from datetime import timezone
from functools import cache
from typing import Union

import pytest
from dirty_equals import IsStr
from inline_snapshot import snapshot

from pydantic_graph import (
    BaseNode,
    End,
    EndSnapshot,
    FullStatePersistence,
    Graph,
    GraphRunContext,
    GraphRuntimeError,
    GraphSetupError,
    NodeSnapshot,
)

from ..conftest import IsFloat, IsNow

pytestmark = pytest.mark.anyio


@dataclass
class Float2String(BaseNode):
    input_data: float

    async def run(self, ctx: GraphRunContext) -> String2Length:
        return String2Length(str(self.input_data))


@dataclass
class String2Length(BaseNode):
    input_data: str

    async def run(self, ctx: GraphRunContext) -> Double:
        return Double(len(self.input_data))


@dataclass
class Double(BaseNode[None, None, int]):
    input_data: int

    async def run(self, ctx: GraphRunContext) -> Union[String2Length, End[int]]:  # noqa: UP007
        if self.input_data == 7:
            return String2Length('x' * 21)
        else:
            return End(self.input_data * 2)


async def test_graph():
    my_graph = Graph(nodes=(Float2String, String2Length, Double))
    assert my_graph.name is None
    assert my_graph._inferred_types == (type(None), int)
    result = await my_graph.run(Float2String(3.14))
    # len('3.14') * 2 == 8
    assert result.output == 8
    assert my_graph.name == 'my_graph'


async def test_graph_history():
    my_graph = Graph[None, None, int](nodes=(Float2String, String2Length, Double))
    assert my_graph.name is None
    assert my_graph._inferred_types == (type(None), int)
    sp = FullStatePersistence()
    result = await my_graph.run(Float2String(3.14), persistence=sp)
    # len('3.14') * 2 == 8
    assert result.output == 8
    assert my_graph.name == 'my_graph'
    assert sp.history == snapshot(
        [
            NodeSnapshot(
                state=None,
                node=Float2String(input_data=3.14),
                start_ts=IsNow(tz=timezone.utc),
                duration=IsFloat(),
            ),
            NodeSnapshot(
                state=None,
                node=String2Length(input_data='3.14'),
                start_ts=IsNow(tz=timezone.utc),
                duration=IsFloat(),
            ),
            NodeSnapshot(
                state=None,
                node=Double(input_data=4),
                start_ts=IsNow(tz=timezone.utc),
                duration=IsFloat(),
            ),
            EndSnapshot(state=None, result=End(data=8), ts=IsNow(tz=timezone.utc)),
        ]
    )
    sp = FullStatePersistence()
    result = await my_graph.run(Float2String(3.14159), persistence=sp)
    # len('3.14159') == 7, 21 * 2 == 42
    assert result.output == 42
    assert sp.history == snapshot(
        [
            NodeSnapshot(
                state=None,
                node=Float2String(input_data=3.14159),
                start_ts=IsNow(tz=timezone.utc),
                duration=IsFloat(),
            ),
            NodeSnapshot(
                state=None,
                node=String2Length(input_data='3.14159'),
                start_ts=IsNow(tz=timezone.utc),
                duration=IsFloat(),
            ),
            NodeSnapshot(
                state=None,
                node=Double(input_data=7),
                start_ts=IsNow(tz=timezone.utc),
                duration=IsFloat(),
            ),
            NodeSnapshot(
                state=None,
                node=String2Length(input_data='xxxxxxxxxxxxxxxxxxxxx'),
                start_ts=IsNow(tz=timezone.utc),
                duration=IsFloat(),
            ),
            NodeSnapshot(
                state=None,
                node=Double(input_data=21),
                start_ts=IsNow(tz=timezone.utc),
                duration=IsFloat(),
            ),
            EndSnapshot(state=None, result=End(data=42), ts=IsNow(tz=timezone.utc)),
        ]
    )
    assert [e.node for e in sp.history] == snapshot(
        [
            Float2String(input_data=3.14159),
            String2Length(input_data='3.14159'),
            Double(input_data=7),
            String2Length(input_data='xxxxxxxxxxxxxxxxxxxxx'),
            Double(input_data=21),
            End(data=42),
        ]
    )


def test_one_bad_node():
    class Float2String(BaseNode):
        async def run(self, ctx: GraphRunContext) -> String2Length:
            raise NotImplementedError()

    class String2Length(BaseNode[None, None, None]):  # pyright: ignore[reportUnusedClass]
        async def run(self, ctx: GraphRunContext) -> End[None]:
            raise NotImplementedError()

    with pytest.raises(GraphSetupError) as exc_info:
        Graph(nodes=(Float2String,))

    assert exc_info.value.message == snapshot(
        '`String2Length` is referenced by `Float2String` but not included in the graph.'
    )


def test_two_bad_nodes():
    class Foo(BaseNode):
        input_data: float

        async def run(self, ctx: GraphRunContext) -> Union[Bar, Spam]:  # noqa: UP007
            raise NotImplementedError()

    class Bar(BaseNode[None, None, None]):
        input_data: str

        async def run(self, ctx: GraphRunContext) -> End[None]:
            raise NotImplementedError()

    class Spam(BaseNode[None, None, None]):
        async def run(self, ctx: GraphRunContext) -> End[None]:
            raise NotImplementedError()

    with pytest.raises(GraphSetupError) as exc_info:
        Graph(nodes=(Foo,))

    assert exc_info.value.message == snapshot("""\
Nodes are referenced in the graph but not included in the graph:
 `Bar` is referenced by `Foo`
 `Spam` is referenced by `Foo`\
""")


def test_three_bad_nodes_separate():
    class Foo(BaseNode):
        input_data: float

        async def run(self, ctx: GraphRunContext) -> Eggs:
            raise NotImplementedError()

    class Bar(BaseNode[None, None, None]):
        input_data: str

        async def run(self, ctx: GraphRunContext) -> Eggs:
            raise NotImplementedError()

    class Spam(BaseNode[None, None, None]):
        async def run(self, ctx: GraphRunContext) -> Eggs:
            raise NotImplementedError()

    class Eggs(BaseNode[None, None, None]):
        async def run(self, ctx: GraphRunContext) -> End[None]:
            raise NotImplementedError()

    with pytest.raises(GraphSetupError) as exc_info:
        Graph(nodes=(Foo, Bar, Spam))

    assert exc_info.value.message == snapshot(
        '`Eggs` is referenced by `Foo`, `Bar`, and `Spam` but not included in the graph.'
    )


def test_duplicate_id():
    class Foo(BaseNode):
        async def run(self, ctx: GraphRunContext) -> Bar:
            raise NotImplementedError()

    class Bar(BaseNode[None, None, None]):
        async def run(self, ctx: GraphRunContext) -> End[None]:
            raise NotImplementedError()

        @classmethod
        @cache
        def get_id(cls) -> str:
            return 'Foo'

    with pytest.raises(GraphSetupError) as exc_info:
        Graph(nodes=(Foo, Bar))

    assert exc_info.value.message == snapshot(IsStr(regex='Node ID `Foo` is not unique — found on <class.+'))


async def test_run_node_not_in_graph():
    @dataclass
    class Foo(BaseNode):
        async def run(self, ctx: GraphRunContext) -> Bar:
            return Bar()

    @dataclass
    class Bar(BaseNode[None, None, None]):
        async def run(self, ctx: GraphRunContext) -> End[None]:
            return Spam()  # type: ignore

    @dataclass
    class Spam(BaseNode[None, None, None]):
        async def run(self, ctx: GraphRunContext) -> End[None]:
            raise NotImplementedError()

    g = Graph(nodes=(Foo, Bar))
    with pytest.raises(GraphRuntimeError) as exc_info:
        await g.run(Foo())

    assert exc_info.value.message == snapshot('Node `test_run_node_not_in_graph.<locals>.Spam()` is not in the graph.')


async def test_run_return_other():
    @dataclass
    class Foo(BaseNode):
        async def run(self, ctx: GraphRunContext) -> Bar:
            return Bar()

    @dataclass
    class Bar(BaseNode[None, None, None]):
        async def run(self, ctx: GraphRunContext) -> End[None]:
            return 42  # type: ignore

    g = Graph(nodes=(Foo, Bar))
    assert g._inferred_types == (type(None), type(None))
    with pytest.raises(GraphRuntimeError) as exc_info:
        await g.run(Foo())

    assert exc_info.value.message == snapshot('Invalid node return type: `int`. Expected `BaseNode` or `End`.')


async def test_next():
    @dataclass
    class Foo(BaseNode):
        async def run(self, ctx: GraphRunContext) -> Bar:
            return Bar()

    @dataclass
    class Bar(BaseNode):
        async def run(self, ctx: GraphRunContext) -> Foo:
            return Foo()

    g = Graph(nodes=(Foo, Bar))
    assert g.name is None
    sp = FullStatePersistence()
    n = await g.next(Foo(), persistence=sp)
    assert n == Bar()
    assert g.name == 'g'
    assert sp.history == snapshot(
        [NodeSnapshot(state=None, node=Foo(), start_ts=IsNow(tz=timezone.utc), duration=IsFloat())]
    )

    assert isinstance(n, Bar)
    n2 = await g.next(n, persistence=sp)
    assert n2 == Foo()

    assert sp.history == snapshot(
        [
            NodeSnapshot(state=None, node=Foo(), start_ts=IsNow(tz=timezone.utc), duration=IsFloat()),
            NodeSnapshot(state=None, node=Bar(), start_ts=IsNow(tz=timezone.utc), duration=IsFloat()),
        ]
    )


async def test_deps():
    @dataclass
    class Deps:
        a: int
        b: int

    @dataclass
    class Foo(BaseNode[None, Deps]):
        async def run(self, ctx: GraphRunContext[None, Deps]) -> Bar:
            assert isinstance(ctx.deps, Deps)
            return Bar()

    @dataclass
    class Bar(BaseNode[None, Deps, int]):
        async def run(self, ctx: GraphRunContext[None, Deps]) -> End[int]:
            assert isinstance(ctx.deps, Deps)
            return End(123)

    g = Graph(nodes=(Foo, Bar))
    sp = FullStatePersistence()
    result = await g.run(Foo(), deps=Deps(1, 2), persistence=sp)

    assert result.output == 123
    assert sp.history == snapshot(
        [
            NodeSnapshot(state=None, node=Foo(), start_ts=IsNow(tz=timezone.utc), duration=IsFloat()),
            NodeSnapshot(state=None, node=Bar(), start_ts=IsNow(tz=timezone.utc), duration=IsFloat()),
            EndSnapshot(state=None, result=End(123), ts=IsNow(tz=timezone.utc)),
        ]
    )
