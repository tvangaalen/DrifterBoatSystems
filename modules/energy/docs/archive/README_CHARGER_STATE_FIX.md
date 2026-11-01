# v0.17.2 — Charger House state display fix

No field mapping was changed.

The problem was the enum decoding:
- CombiMaster field 1: 0=Off, 1=Bulk, 2=Absorption, 3=Float
- Mass Charger field 1: 2=Bulk, 3=Absorption, 4=Float

v0.17.1 incorrectly used the Mass Charger enum for Charger House, which could
leave the state line blank or mislabel it.
