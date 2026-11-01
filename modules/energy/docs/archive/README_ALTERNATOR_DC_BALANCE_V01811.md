# v0.18.11 — Alternator / Other DC balance state fix

The DC balance solver now uses Alpha Pro field 5 (actual charging state), not shaft rotation, to determine whether alternator current is zero or must be calculated.

- Alpha states 1/2/3 (Bulk/Absorption/Float): alternator is electrically active; calculate alternator current from the learned total-house-load baseline.
- Alpha states 0/5 (Off/Stopped): alternator current is zero; learn/update the total-house-load baseline even if the engine/alternator shafts are still turning.
- Shaft rotation remains exposed diagnostically as `shaft_running` but no longer gates the current solver.
- Alternator ON/OFF control behavior from v0.18.10 is unchanged.
