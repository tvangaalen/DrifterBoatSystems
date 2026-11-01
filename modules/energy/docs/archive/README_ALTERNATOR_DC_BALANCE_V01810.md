# v0.18.10 — Alternator / Other DC balance and Stop Charge behavior

## DC current model

The House MasterShunt current is signed and already includes the effect of all loads on the house battery bus, including Charger Start and Charger Bow.

When the alternator is stopped:

    TotalHouseLoad_A = ChargerHouse_A + Solar_A - HouseBattery_A
    OtherDC_A = max(0, TotalHouseLoad_A - ChargerStart_A - ChargerBow_A - EngineECU_A)

`TotalHouseLoad_A` is low-pass filtered (alpha 0.25) and retained as the baseline.

When the alternator is running:

    Alternator_A = max(0, HouseBattery_A + TotalHouseLoadBaseline_A - ChargerHouse_A - Solar_A)
    OtherDC_A = max(0, TotalHouseLoadBaseline_A - ChargerStart_A - ChargerBow_A - EngineECU_A)

This avoids double-counting the individually displayed DC loads.

## Alternator control

OFF remains Alpha Pro Stop Charge field 39 = 1 with commit field 40.

ON now only clears Stop Charge: field 39 = 0 with commit field 40. It does not issue a Bulk command. This release intentionally tests whether the Alpha Pro resumes normal charging automatically after Stop Charge is removed.

Alpha Pro field 5 value 5 remains decoded as `Stopped`.
