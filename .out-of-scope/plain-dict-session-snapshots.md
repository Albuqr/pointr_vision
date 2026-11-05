# Plain dicts instead of frozen session snapshots

Session snapshots in `services/edge/session/folder.py` stay deeply immutable (D-065: "Snapshots
contain only immutable values"). We do not replace them with plain dicts.

## Why this is out of scope

The saving is about 30 lines (`_freeze`, `_thaw`, `_snapshot_data` and an empty `RunSnapshot`
subclass). Reversing D-065 would also drop its test,
`test_T2_snapshot_is_deeply_immutable_and_detached`, and the guarantee that a consumer cannot
change what another consumer reads. The decision was made deliberately and the saving is too small
to reverse it.

Reconsider if the freeze/thaw code becomes a real maintenance cost.

## Prior requests

- #113: "Audit: plain dicts instead of frozen session snapshots (reverses D-065)" (decided 2026-11-03, parent #106)
