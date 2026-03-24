"""Tests for real ast.parse symbol extraction in _file_ast_skeleton (WS33-010)."""

from __future__ import annotations

from apiserver.native_tools import NativeToolExecutor


# ── Valid Python: ast.parse path ────────────────────────────────


VALID_PY_SOURCE = """\
import os
from pathlib import Path


def top_level_func():
    pass


async def top_level_async():
    pass


class Animal:
    def speak(self):
        pass

    async def fetch_data(self):
        pass

    class Inner:
        def inner_method(self):
            pass
"""


class TestAstParseValidPython:
    """ast.parse should produce correct function / class / method entries."""

    def test_top_level_function(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(VALID_PY_SOURCE, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any(n.startswith("function top_level_func") for n in names)

    def test_top_level_async_function(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(VALID_PY_SOURCE, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any(n.startswith("async_function top_level_async") for n in names)

    def test_class_detected(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(VALID_PY_SOURCE, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any(n.startswith("class Animal") for n in names)

    def test_method_prefixed_with_class(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(VALID_PY_SOURCE, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any("Animal.speak" in n for n in names)
        assert any("Animal.fetch_data" in n for n in names)

    def test_async_method_type(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(VALID_PY_SOURCE, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any(n.startswith("async_function Animal.fetch_data") for n in names)

    def test_line_range_present(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(VALID_PY_SOURCE, 300)
        # Every symbol should contain a [L<start>-<end>] range
        for s in symbols:
            assert "[L" in s and "-" in s.split("[L")[1], f"Missing line range in: {s}"

    def test_symbol_count(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(VALID_PY_SOURCE, 300)
        # top_level_func, top_level_async, Animal, Animal.speak,
        # Animal.fetch_data, Animal.Inner, Animal.Inner.inner_method
        assert len(symbols) == 7

    def test_max_symbols_respected(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(VALID_PY_SOURCE, 3)
        assert len(symbols) <= 3


# ── Nested class methods are correctly prefixed ─────────────────


class TestNestedClassPrefix:
    """Nested class methods get ClassName.Inner.method_name prefix."""

    def test_nested_class_name(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(VALID_PY_SOURCE, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any(n.startswith("class Animal.Inner") for n in names)

    def test_nested_method_prefix(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(VALID_PY_SOURCE, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any("Animal.Inner.inner_method" in n for n in names)


# ── Syntax error: falls back to empty (caller uses regex) ──────


BROKEN_PY_SOURCE = """\
def valid_func():
    pass

class Oops(
    # missing closing paren and colon
"""


class TestSyntaxErrorFallback:
    """SyntaxError in ast.parse should return empty list (regex fallback)."""

    def test_returns_empty_on_syntax_error(self) -> None:
        symbols = NativeToolExecutor._extract_py_symbols_ast(BROKEN_PY_SOURCE, 300)
        assert symbols == []

    def test_regex_fallback_catches_symbols(self) -> None:
        """Regex path still works for the same broken source."""
        lines = BROKEN_PY_SOURCE.splitlines()
        symbols = NativeToolExecutor._extract_symbols_regex(".py", lines, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any("valid_func" in n for n in names)
        assert any("Oops" in n for n in names)


# ── Non-Python files always use regex ───────────────────────────


TS_SOURCE = """\
import { useState } from 'react';

export function greet(name: string): string {
    return `Hello, ${name}`;
}

class UserService {
    async fetchUser(id: number) {}
}

const handler = (event: Event) => {};
"""


class TestNonPythonRegex:
    """Non-Python extensions must go through regex path."""

    def test_ts_function_detected(self) -> None:
        lines = TS_SOURCE.splitlines()
        symbols = NativeToolExecutor._extract_symbols_regex(".ts", lines, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any("greet" in n for n in names)

    def test_ts_class_detected(self) -> None:
        lines = TS_SOURCE.splitlines()
        symbols = NativeToolExecutor._extract_symbols_regex(".ts", lines, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any("UserService" in n for n in names)

    def test_ts_arrow_const_detected(self) -> None:
        lines = TS_SOURCE.splitlines()
        symbols = NativeToolExecutor._extract_symbols_regex(".ts", lines, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any("handler" in n for n in names)

    def test_unknown_ext_uses_generic_regex(self) -> None:
        lines = ["class Foo:", "def bar():"].copy()
        symbols = NativeToolExecutor._extract_symbols_regex(".rb", lines, 300)
        names = [s.split(": ", 1)[1] for s in symbols]
        assert any("Foo" in n for n in names)
        assert any("bar" in n for n in names)
