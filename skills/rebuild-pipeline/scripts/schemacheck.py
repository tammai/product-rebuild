"""schemacheck.py — validate data against this plugin's JSON Schemas, with no pip install.

WHY IT EXISTS. validate.mjs compiled schemas/*.schema.json with ajv. Python's stdlib has no JSON
Schema validator, and the full `jsonschema` package drags in a dependency tree for a handful of
keywords. The schemas here use a small, fixed vocabulary, so this implements exactly that.

IT REFUSES WHAT IT DOES NOT KNOW. A schema keyword this module has no code for would otherwise be
skipped, and "the schema says X but nothing checks X" is the failure a validator must not have.
Compiling a schema that uses an unsupported keyword raises SchemaUnsupported naming it, so adding
`exclusiveMinimum` to a schema fails loudly until it is implemented here. eval/yamlio_schema.py
compiles every shipped schema, which is what makes that a test and not a hope.

Messages follow ajv's wording and its `data/path` prefix, so a finding reads as it did before.
`allErrors` behaviour is kept: every violation is collected, not just the first.

Library, not an entry point.
"""
from __future__ import annotations

import datetime as _dt
import json
import re

# Keywords that validate, and keywords that only annotate or define. Anything else is refused.
_VALIDATING = {
    "type", "properties", "required", "additionalProperties", "items", "minItems", "maxItems",
    "uniqueItems", "minLength", "maxLength", "minimum", "maximum", "enum", "const", "pattern",
    "format", "propertyNames", "anyOf", "allOf", "oneOf", "not", "if", "then", "else", "$ref",
}
_ANNOTATION = {"$schema", "$id", "$comment", "title", "description", "default", "examples",
               "definitions", "$defs"}


class SchemaUnsupported(ValueError):
    pass


_DATE_TIME = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:[Zz]|[+-](\d{2}):(\d{2}))$")
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[^\s]*$")


def _format_ok(name: str, value: str) -> bool:
    if name == "date-time":
        m = _DATE_TIME.match(value)
        if not m:
            return False
        y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
        try:
            _dt.date(y, mo, d)
        except ValueError:
            return False
        return h <= 23 and mi <= 59 and s <= 60  # 60: a leap second is valid RFC 3339
    if name == "uri":
        return bool(_URI.match(value))
    raise SchemaUnsupported(f'format "{name}" is not implemented in schemacheck.py')


def _is_type(value, t: str) -> bool:
    if t == "null":
        return value is None
    if t == "boolean":
        return isinstance(value, bool)
    if t == "string":
        return isinstance(value, str)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "integer":
        # A YAML `1.0` is a float here and the number 1 in JavaScript; the old validator took it.
        return (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, float) and value.is_integer())
    raise SchemaUnsupported(f'type "{t}" is not a JSON Schema type')


def _same(a, b) -> bool:
    """JSON equality: 1 and true are different, 1 and 1.0 are the same."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _ptr(key: str) -> str:
    """A property name as a JSON Pointer segment, as ajv writes it: `/` is `~1`, `~` is `~0`."""
    return key.replace("~", "~0").replace("/", "~1")


class Validator:
    def __init__(self, schema: dict):
        self.root = schema
        self._patterns: dict[str, re.Pattern] = {}
        self._check_supported(schema, "#")

    # -- compile-time walk: refuse keywords we cannot enforce -------------------------------------
    def _check_supported(self, node, where: str) -> None:
        if isinstance(node, bool) or not isinstance(node, dict):
            return
        for key, sub in node.items():
            if key in _ANNOTATION:
                if key in ("definitions", "$defs") and isinstance(sub, dict):
                    for name, s in sub.items():
                        self._check_supported(s, f"{where}/{key}/{name}")
                continue
            if key not in _VALIDATING:
                raise SchemaUnsupported(f'schema keyword "{key}" at {where} is not implemented in schemacheck.py; '
                                        f"implement it there (and test it) before using it in a schema")
            if key == "properties":
                for name, s in sub.items():
                    self._check_supported(s, f"{where}/properties/{name}")
            elif key in ("items", "additionalProperties", "propertyNames", "not", "if", "then", "else"):
                self._check_supported(sub, f"{where}/{key}")
            elif key in ("anyOf", "allOf", "oneOf"):
                for i, s in enumerate(sub):
                    self._check_supported(s, f"{where}/{key}/{i}")
            elif key == "format":
                _format_ok(sub, "x")  # raises for a format we do not know
            elif key == "$ref":
                self._resolve(sub)

    def _resolve(self, ref: str):
        m = re.match(r"^#/(definitions|\$defs)/(.+)$", ref)
        if not m or m.group(1) not in self.root or m.group(2) not in self.root[m.group(1)]:
            raise SchemaUnsupported(f'$ref "{ref}" must point at a local #/definitions/<name>')
        return self.root[m.group(1)][m.group(2)]

    # -- validation -------------------------------------------------------------------------------
    def errors(self, data) -> list[str]:
        out: list[str] = []
        self._validate(self.root, data, "", out)
        return out

    def is_valid(self, data) -> bool:
        return not self.errors(data)

    def errors_text(self, data, separator: str = ", ") -> str:
        return separator.join(self.errors(data))

    def _pattern(self, p: str) -> re.Pattern:
        if p not in self._patterns:
            self._patterns[p] = re.compile(p)
        return self._patterns[p]

    def _validate(self, schema, value, path: str, out: list[str]) -> None:
        if schema is True or schema == {}:
            return
        if schema is False:
            out.append(f"data{path} must NOT be valid")
            return
        add = lambda msg, p=path: out.append(f"data{p} {msg}")  # noqa: E731

        if "$ref" in schema:
            self._validate(self._resolve(schema["$ref"]), value, path, out)
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(value, t) for t in types):
                add("must be " + ",".join(types))
                return  # ajv stops at a type mismatch for the keywords of that type
        if "enum" in schema and not any(_same(value, e) for e in schema["enum"]):
            add("must be equal to one of the allowed values")
        if "const" in schema and not _same(value, schema["const"]):
            add("must be equal to constant")

        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                add(f"must NOT have fewer than {schema['minLength']} characters")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                add(f"must NOT have more than {schema['maxLength']} characters")
            if "pattern" in schema and not self._pattern(schema["pattern"]).search(value):
                add(f'must match pattern "{schema["pattern"]}"')
            if "format" in schema and not _format_ok(schema["format"], value):
                add(f'must match format "{schema["format"]}"')
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                add(f"must be >= {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                add(f"must be <= {schema['maximum']}")

        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                add(f"must NOT have fewer than {schema['minItems']} items")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                add(f"must NOT have more than {schema['maxItems']} items")
            if schema.get("uniqueItems"):
                for i in range(len(value)):
                    dup = next((j for j in range(i) if _same(value[i], value[j])), None)
                    if dup is not None:
                        add(f"must NOT have duplicate items (items ## {i} and {dup} are identical)")
                        break
            if "items" in schema:
                for i, item in enumerate(value):
                    self._validate(schema["items"], item, f"{path}/{i}", out)

        if isinstance(value, dict):
            for key in schema.get("required", []):
                if key not in value:
                    add(f"must have required property '{key}'")
            props = schema.get("properties", {})
            for key, sub in props.items():
                if key in value:
                    self._validate(sub, value[key], f"{path}/{_ptr(key)}", out)
            if "additionalProperties" in schema:
                ap = schema["additionalProperties"]
                for key in value:
                    if key in props:
                        continue
                    if ap is False:
                        add("must NOT have additional properties")
                    elif ap is not True:
                        self._validate(ap, value[key], f"{path}/{_ptr(key)}", out)
            if "propertyNames" in schema:
                for key in value:
                    sub: list[str] = []
                    self._validate(schema["propertyNames"], key, path, sub)
                    if sub:
                        add(f"property name '{key}' is invalid")

        if "anyOf" in schema and not any(not self._sub_errors(s, value, path) for s in schema["anyOf"]):
            add("must match a schema in anyOf")
        if "oneOf" in schema:
            n = sum(1 for s in schema["oneOf"] if not self._sub_errors(s, value, path))
            if n != 1:
                add("must match exactly one schema in oneOf")
        for s in schema.get("allOf", []):
            self._validate(s, value, path, out)
        if "not" in schema and not self._sub_errors(schema["not"], value, path):
            add("must NOT be valid")
        if "if" in schema:
            if not self._sub_errors(schema["if"], value, path):
                if "then" in schema:
                    self._validate(schema["then"], value, path, out)
            elif "else" in schema:
                self._validate(schema["else"], value, path, out)

    def _sub_errors(self, schema, value, path) -> list[str]:
        sub: list[str] = []
        self._validate(schema, value, path, sub)
        return sub


def compile_schema(path: str) -> Validator:
    with open(path, "r", encoding="utf-8") as f:
        return Validator(json.load(f))
