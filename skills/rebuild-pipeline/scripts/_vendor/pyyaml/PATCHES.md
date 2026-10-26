# Changes made to the vendored PyYAML 6.0.3

- `yaml/__init__.py` is replaced by a load-only one (the dumper, emitter, representer, serializer
  and libyaml bindings are not shipped).
- `yaml/scanner.py`: `?` no longer ends a plain scalar in flow context (search for `PATCHED`), so
  `{path: api/ok?x=1}` parses as it does under the YAML 1.2 core schema.

Everything else is PyYAML as released, MIT (see LICENSE).
