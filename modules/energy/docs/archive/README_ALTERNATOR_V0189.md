# v0.18.9 — Alpha Pro Stopped state and restart sequence

Hardware feedback established that Alpha Pro charger-state field 5 value `5` is shown by MasterView as `Stopped`. The dashboard now decodes `5 = Stopped`.

The OFF command remains field 39 (`Stop charge`) = 1.0 + commit field 40.

The ON command now first clears the latched Stop Charge request:

1. field 39 (`Stop charge`) = 0.0 + commit field 40;
2. wait briefly;
3. field 33 (`Bulk`) = 1.0 + commit field 34.

ON verification accepts Alpha Pro states Bulk, Absorption or Float. OFF verification expects state 5 (`Stopped`).

PWA cache: `mastervolt-v0.18.9-shell`.
