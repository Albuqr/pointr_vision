# Removing Track R contract scaffolding

The contract column and enum constants in `services/edge/contract.py`, `fusion.schema.json` and the
always-null `RunMeta` fields (`clock`, `objects`, `gaps`, `outages`) stay, even though only tests
read most of them today.

## Why this is out of scope

R2 to R6 are the next slices and each one writes the format its constants describe. Removing the
scaffolding now means adding it back slice by slice. While it is in place, the tests in
`tests/test_contracts_track_r.py` also stop `docs/DATA_CONTRACTS.md` and the code drifting apart.
The saving is about 240 lines, which does not outweigh that.

Reconsider if R2 to R6 are dropped or the contract is restructured.

## Prior requests

- #109: "Audit: drop Track R scaffolding that only tests read" (decided 2026-11-03, parent #106)
