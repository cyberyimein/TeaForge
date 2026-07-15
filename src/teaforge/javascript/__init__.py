"""Structural JavaScript/TypeScript evidence used by framework adapters."""

from .syntax import (
    JavaScriptCall,
    JavaScriptFunction,
    JavaScriptImport,
    JavaScriptSyntaxError,
    JavaScriptTestCase,
    extract_imports,
    extract_test_cases,
    parse_calls,
    parse_source_functions,
    source_defines_symbol,
)

__all__ = [
    "JavaScriptCall",
    "JavaScriptFunction",
    "JavaScriptImport",
    "JavaScriptSyntaxError",
    "JavaScriptTestCase",
    "extract_imports",
    "extract_test_cases",
    "parse_calls",
    "parse_source_functions",
    "source_defines_symbol",
]
