from typing import (
    Hashable,
    Iterable,
    Mapping,
    TypeVar,
)


T = TypeVar("T", bound=Hashable)


def detect_cycles(graph: Mapping[T, Iterable[T]]) -> None:
    visited = set()
    stack = set()

    def visit(node: T) -> None:
        if node in stack:
            raise Exception(f"Cycle detected in variables: {node}")
        if node in visited:
            return

        stack.add(node)
        for child in graph.get(node, []):
            visit(child)

        stack.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
