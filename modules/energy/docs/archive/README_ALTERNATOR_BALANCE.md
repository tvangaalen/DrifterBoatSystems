# v0.16 — Alternator current from the house DC balance

The Alpha Pro does not expose a trustworthy alternator output-current field.

v0.16 therefore derives alternator current from the house-bus current balance.

## Sign convention

House MasterShunt current:

```text
positive = current INTO the house battery (charging)
negative = current OUT of the house battery (discharging)
```

The source/load balance is:

```text
Alternator A =
    House battery A
  + Charger Start A
  + Charger Bowthruster A
  + Engine ECU A
  + Other DC Loads A
  - Charger House A
  - Solar Charge A
```

## Avoiding a circular calculation

Alternator current and `Other DC Loads` cannot both be solved from the same
single MasterShunt equation at the same instant.

v0.16 resolves this by using the Alpha Pro shaft signals:

```text
field 11 = Alternator shaft
field 12 = Engine shaft
```

When both indicate the engine/alternator is stopped, alternator current is
known to be 0 A. The application can then solve for the actual `Other DC Loads`:

```text
Other DC Loads A =
    Charger House A
  + Solar A
  - House battery A
  - Charger Start A
  - Charger Bowthruster A
  - Engine ECU A
```

That value is low-pass filtered as a baseline.

When the engine runs, that independent baseline is used in the alternator
equation above.

This makes the calculation non-circular.

## Verified source fields

### Solar ChargeMaster

```text
field 4 = Solar/PV voltage
field 5 = Charge current
field 6 = Battery/output voltage
Solar W = field 6 * field 5
```

### Alpha Pro

```text
field 11 = Alternator shaft
field 12 = Engine shaft
field 14 = Alternator voltage
field 32 = Alternator temperature
```

Alternator watts are:

```text
Alternator W = field 14 * derived Alternator A
```

When the engine is stopped the dashboard explicitly reports alternator current
as 0 A / 0 W instead of using Alpha Pro field 21.
