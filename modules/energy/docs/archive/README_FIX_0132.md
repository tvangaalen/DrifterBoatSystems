# v0.13.2 fix

v0.13.1 fixed the `MasterBusService` indentation problem, but the same code
generation error also affected `masterbus_control_discovery.py`.

`_meta_with_extra()` and `list_options()` were accidentally created at module
scope instead of as methods of `ControlDiscovery`.

That caused:

```text
AttributeError: 'ControlDiscovery' object has no attribute 'list_options'
```

v0.13.2 rebuilds `masterbus_control_discovery.py` cleanly and extends
`self_check.py` so it checks both classes.

Run:

```powershell
cd C:\temp\mastervoltproject;
py self_check.py
```

Expected final line:

```text
All structural checks: OK
```

Then run:

```powershell
cd C:\temp\mastervoltproject;
py ecu_dropdown_probe.py
```
