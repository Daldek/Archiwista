# Copies of the Nogat standard

Verbatim copies (ERR-3, AGI-4.1, DEV-15.6) of the files below from the
[Nogat](https://github.com/Daldek/Nogat) repository; Nogat's
`uv run scripts/ecosystem.py drift` reports each copy as current, behind or modified.

- `error_registry.json` (Nogat `standards/error_registry.json` at commit `7786271`, the
  standard numbered 1.0; SHA-256
  `8a5b015414b039cc89cc06d2f4947834804403da35c16bcc863f44e1b54dcaa3`): error codes, exit
  codes and HTTP statuses. `src/archiwista/_errors.py` is generated from it with
  `uv run scripts/generate_errors.py`.
- `result-1.schema.json`, `error-1.schema.json`, `commands-1.schema.json` (Nogat
  `schemas/agent/` at commit `cc656e7`, unchanged at `7786271`): the schemas of the result
  envelope, the error document and the command catalog. `tests/contract/` validates
  Archiwista's error documents against `error-1`.
- `handoff-1.schema.json` (Nogat `schemas/exchange/handoff-1.schema.json` at commit
  `b46eb5b` of `develop`, last changed in `48781c7`, with `node_provenance` and the optional
  `attribution` and `terms_notice` of DEV §20, whose examples link the terms (ECO-065); SHA-256
  `c26ce043b292284fa7e8f995589fee09fd5ffa046efb61c4b3736619b8b71d08`): the envelope
  `nogat-handoff/1` of a station's series handed to Hydrolog (A-ADR-052, A-ADR-054,
  A-ADR-055);
  `tests/integration/test_station_statistics_api.py` validates Archiwista's hand-offs against
  it, and their payload against Hydrolog's `../hydrolog/hydrolog-series-1.schema.json`
  (Hydrolog `src/hydrolog/schemas/` at commit `35054bf` of `feature/series-handoff`; SHA-256
  `39570da20717c28b482bc66e6ede800714b6b92e810278976a8017736f9053c2`).

Nogat's GUI kit and the marks of the GUIs are copied the same way into
`src/archiwista/web/nogat/` (A-ADR-054).

Do not edit these files; copy them again when Nogat changes them.
