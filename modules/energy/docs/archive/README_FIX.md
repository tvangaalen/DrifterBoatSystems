# v0.13.1 fix

v0.13 contained an indentation error in `masterbus_service.py`.

The ECU dropdown helper block was placed at module scope, which also caused
`open()`, `close()`, and later methods to become nested under the wrong
function. Therefore `MasterBusService` no longer had an `open()` method.

v0.13.1 fixes the class indentation and adds a structural regression check.

Run:

```powershell
cd C:\temp\mastervoltproject;
py self_check.py
```

Expected:

```text
MasterBusService structure: OK
```

Then run:

```powershell
cd C:\temp\mastervoltproject;
py ecu_dropdown_probe.py
```
