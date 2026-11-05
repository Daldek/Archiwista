# Copies of the Nogat standard

Verbatim copies (ERR-3, AGI-4.1) of the files below, from the standard 2.1 of the
[Nogat](https://github.com/Daldek/Nogat) repository at commit `cc656e7` (the tag
`std-2.1` does not exist yet; replace the copies by the tag when it does):

- `error_registry.json` (Nogat `standards/error_registry.json`): error codes, exit
  codes and HTTP statuses. `src/archiwista/_errors.py` is generated from it with
  `uv run scripts/generate_errors.py`.
- `result-1.schema.json`, `error-1.schema.json`, `commands-1.schema.json` (Nogat
  `schemas/agent/`): the schemas of the result envelope, the error document and the
  command catalog. `tests/contract/` validates Archiwista's error documents against
  `error-1`.
- `handoff-1.schema.json` (Nogat `schemas/exchange/handoff-1.schema.json` at commit
  `8727f6e`, unchanged on `develop`; SHA-256
  `15c82f6a9e0107ddf1c6846f8053d7da9991c1e91679f93d5da4a2fadf6fd6e4`): the envelope
  `nogat-handoff/1` of a station's series handed to Hydrolog (A-ADR-052);
  `tests/integration/test_station_statistics_api.py` validates Archiwista's hand-offs against
  it, and their payload against Hydrolog's `../hydrolog/hydrolog-series-1.schema.json`
  (Hydrolog `src/hydrolog/schemas/` at commit `35054bf` of `feature/series-handoff`; SHA-256
  `39570da20717c28b482bc66e6ede800714b6b92e810278976a8017736f9053c2`).

Do not edit these files; copy them again when the standard changes.
