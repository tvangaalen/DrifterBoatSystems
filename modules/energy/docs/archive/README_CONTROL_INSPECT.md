# v0.11.1 focused control inspection

This patch adds `control_inspect.py`.

It is deliberately read-only. It inspects:

- Charger Start: fields 60–67
- Charger Bowthruster: fields 60–67
- Yanmar interface: fields 54–58

For each field it prints:
- MasterBus protocol
- visualization type
- writable flag
- current numeric value
- field name

Run:

```powershell
cd C:\temp\mastervoltproject;
py control_inspect.py
```

Paste the complete output into ChatGPT.

The purpose is to verify the Mass Charger `On/Standby` field and determine the
current/value semantics of the Yanmar `Power` dropdown before any new write
control is enabled.
