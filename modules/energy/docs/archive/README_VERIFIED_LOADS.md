# v0.16.1 — verified charger and ECU load fields

## Charger Start

House-bus load uses:

```text
field 4 = Input voltage
field 5 = Input current
input watts = field 4 * field 5
```

Fields 6/7 are the charger output side and are not used for the house-bus load.

## Charger Bowthruster

House-bus load uses:

```text
field 4 = Input voltage
field 5 = Input current
input watts = field 4 * field 5
```

Fields 6/7 are output voltage/current.

## Engine ECU

Verified fields:

```text
field 39 = DC Input voltage
field 40 = DC Output voltage
field 41 = DC Output current
field 43 = Mac/Magic On control
```

No direct DC-input-current field exists.

v0.16.1 estimates ECU house-bus load with an efficiency of:

```text
eta = 0.85
```

Calculation:

```text
Pout = Vout * Iout
Pin  = Pout / 0.85
Iin  = Pin / Vin
```

Using the snapshot values:

```text
Vin  = 13.35 V
Vout = 12.82 V
Iout = 0.06 A

Pout = 0.7692 W
Pin  ≈ 0.905 W
Iin  ≈ 0.0678 A
```

85% is a conservative estimate for this low-power operating point, where fixed
electronics overhead makes peak converter-efficiency figures unrealistic.
