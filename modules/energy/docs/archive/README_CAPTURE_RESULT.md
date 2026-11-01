# MasterAdjust capture result — Engine ECU Power

The USBPcap capture resolves the write protocol.

MasterAdjust continuously reads fields 38–41 (`0x26`–`0x29`) and field 43
(`0x2B`) from `INT Yanmar ECU` at address `3AE394`.

At the user's Power ON -> OFF action, MasterAdjust sent:

```text
CAN ID: 0x183AE394
DATA:   2B 00 00 00 00 00
```

This is field 43 (`0x002B`) with float value `0.0`.

At Power OFF -> ON, MasterAdjust sent:

```text
CAN ID: 0x183AE394
DATA:   2B 00 00 00 80 3F
```

This is field 43 with IEEE-754 float value `1.0`.

No companion commit write was observed around either transaction.

Therefore the operational Engine ECU power control used by MasterAdjust is:

```text
Field 43 — Mac/Magic On
OFF = 0.0
ON  = 1.0
```

Field 56 `Power` is configuration metadata/a separate setting and is not the
runtime power command used by MasterAdjust for this operation.

v0.15 maps the web Engine ECU ON/OFF button to field 43.
