"""yamlio.py — read YAML the way the Node scripts' `yaml` package did, with no pip install.

WHY IT EXISTS. Every workbench file the pipeline checks (findings, features, slices, locks,
progress, sources.yaml) is YAML written partly by language models, and the checks around them are
only as good as the parse. A hand-written parser for "the YAML subset we use" misreads a folded
scalar or a quoted colon silently and the validator then reports on data that is not what the file
says. So this wraps PyYAML's loader (vendored under _vendor/pyyaml, MIT, load-only) instead.

WHY IT IS NOT JUST yaml.safe_load. PyYAML implements YAML 1.1, and the files were written for the
1.2 core schema the old scripts parsed with. Left alone, PyYAML would:
  - read `no`, `yes`, `on`, `off` as booleans: a feature named `no`, or `status: off`, changes type;
  - read `2026-10-26` as a datetime.date, which fails every schema that says `type: string`;
  - read `1:30` as the integer 90 (sexagesimal) and `0755` as octal 493;
  - keep the LAST of two identical keys, so a duplicated `id:` passes silently. The old
    validate.mjs parsed with `uniqueKeys: true` for exactly this reason: a duplicate key in a
    findings file is a lost finding, not a style issue.
All four are turned off below. Anything else (anchors, flow collections, block scalars) is
PyYAML's own and is the point of using it.

One change is made inside the vendored scanner itself (marked PATCHED in _vendor/pyyaml/yaml/scanner.py):
PyYAML ends a flow-style plain scalar at `?`, so `{path: api/ok?x=1}` failed to parse where the 1.2
core schema, and the old scripts' parser, accept it. Recorded traffic carries URLs with query strings.

`<<` merge keys are NOT expanded, matching the 1.2 core schema: they load as an ordinary key.

Library, not an entry point. Importing it puts _vendor/pyyaml on sys.path, which is why the
vendored copy ships beside the scripts: a workbench's scripts/ directory carries both.
"""
from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_HERE, "_vendor", "pyyaml")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import yaml  # noqa: E402  (vendored; see _VENDOR)
from yaml.constructor import ConstructorError, SafeConstructor  # noqa: E402
from yaml.resolver import BaseResolver  # noqa: E402


class YamlError(ValueError):
    """A parse failure, with the 1-based position when PyYAML gave one."""

    def __init__(self, message: str, line: int | None = None, column: int | None = None):
        super().__init__(message)
        self.line = line
        self.column = column


class _Resolver(BaseResolver):
    pass


# Core schema, in the order the first-character lookup tries them: int before float.
_Resolver.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))
_Resolver.add_implicit_resolver(
    "tag:yaml.org,2002:int", re.compile(r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$"), list("-+0123456789"))
_Resolver.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"),
    list("-+0123456789."))
_Resolver.add_implicit_resolver(
    "tag:yaml.org,2002:null", re.compile(r"^(?:~|null|Null|NULL|)$"), ["~", "n", "N", ""])


class _Constructor(SafeConstructor):
    def construct_yaml_int(self, node):
        value = self.construct_scalar(node)
        if re.match(r"^[-+]?[0-9]+$", value):
            return int(value, 10)  # '007' is 7, not octal
        return int(value, 0)  # 0o17, 0x1f

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            raise ConstructorError(None, None, "expected a mapping node, but found %s" % node.id, node.start_mark)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            try:
                hash(key)
            except TypeError:
                raise ConstructorError("while constructing a mapping", node.start_mark,
                                       "found unhashable key", key_node.start_mark)
            if key in mapping:
                raise ConstructorError("while constructing a mapping", node.start_mark,
                                       "Map keys must be unique; %r is repeated" % (key,), key_node.start_mark)
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


_Constructor.add_constructor("tag:yaml.org,2002:int", _Constructor.construct_yaml_int)
# `<<` is an ordinary key in the 1.2 core schema; drop the 1.1 merge resolver SafeConstructor
# would otherwise honour (flatten_mapping is never called, since construct_mapping is replaced).


class _Loader(yaml.reader.Reader, yaml.scanner.Scanner, yaml.parser.Parser, yaml.composer.Composer,
              _Constructor, _Resolver):
    def __init__(self, stream):
        yaml.reader.Reader.__init__(self, stream)
        yaml.scanner.Scanner.__init__(self)
        yaml.parser.Parser.__init__(self)
        yaml.composer.Composer.__init__(self)
        _Constructor.__init__(self)
        _Resolver.__init__(self)


def load(text: str):
    """Parse one YAML document. An empty document is None. Raises YamlError."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    loader = _Loader(text)
    try:
        return loader.get_single_data()
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
        problem = getattr(e, "problem", None) or str(e)
        context = getattr(e, "context", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        raise YamlError(f"{context + ': ' if context and problem != context else ''}{problem}{where}",
                        mark.line + 1 if mark else None, mark.column + 1 if mark else None) from None
    finally:
        loader.dispose()


def load_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return load(f.read())
