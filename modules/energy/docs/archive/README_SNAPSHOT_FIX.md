# v0.15.4 snapshot fix

`masterbus_snapshot.py` still imported the legacy class:

```text
MasterBusDiscovery
```

but the current `masterbus_discovery.py` no longer exports that class. That is
why v0.15.3 failed before any USB communication occurred.

The snapshot utility has been rebuilt against the current
`MasterBusService` + `ControlDiscovery` implementation.

Discovery module currently contains classes:

```text
['Discovery']
```

Run the same commands as before, for example:

```powershell
cd C:\temp\mastervoltproject;
py masterbus_snapshot.py --device 31B483 --all-fields
```

This utility is read-only.
