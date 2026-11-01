# v0.18.8 — Alternator current and ON/OFF control

## Alternator current
The displayed alternator current now follows the requested rule exactly:

```
Alternator A = signed MasterShunt House A + all DC load A
```

DC loads included are Charger Start, Charger Bow, Engine ECU and Other DC.
Charger House and Solar are source currents and are not subtracted.
The final source current is clamped at 0 A.

## Alternator control
The previous one-way Float/OFF action was removed. The Alternator tile now has
the same ON/OFF behavior as the other source controls:

- ON: Alpha Pro field 33 (`Bulk`) = 1.0, then commit field 34.
- OFF: Alpha Pro field 39 (`Stop charge`) = 1.0, then commit field 40.
- Actual charging state is read from Alpha Pro field 5. Bulk, Absorption and
  Float are displayed as ON; Off is displayed as OFF.

PWA cache: `mastervolt-v0.18.8-shell`.
