# v0.15.5 snapshot speed optimization

`masterbus_snapshot.py` now uses the known device-specific `max_index` from
`masterbus_registry.DEVICE_INFO` instead of scanning all 256 possible fields.

Examples:

- Solar ChargeMaster: 0..20
- Alpha Pro: 0..49
- Start/Bow Mass Chargers: 0..67
- Yanmar interface: 0..64

This makes snapshots substantially faster.

You can still override the range manually:

```powershell
cd C:\temp\mastervoltproject;
py masterbus_snapshot.py --device 31B483 --all-fields --max-index 20
```

Normal use does not require `--max-index`.
