# ECU Power write re-check — v0.14.2

The failed v0.14 test should be interpreted more narrowly than before.

We already knew:

```text
54  Charger on   CheckBox   RW
55  <unnamed>    Float      RW

56  Power        DropDown   RW
57  <unnamed>    Float      RW

58  Charger      DropDown   RW
```

That structure strongly resembles the proven CombiMaster control pairs:

```text
19 Inverter  -> hidden field 20
21 Charger   -> hidden field 22
```

On the CombiMaster, the visible field write is followed by the fixed MasterBus
commit token on the adjacent hidden field.

Therefore the failed test:

```text
write field 56 only
readback remained 1
```

does NOT yet prove that Power cannot be written through Btm1. It may simply
prove that we omitted the companion commit write to field 57.

v0.14.2 adds a targeted reversible test:

```powershell
cd C:\temp\mastervoltproject;
py ecu_commit_test.py
```

Then:

```powershell
cd C:\temp\mastervoltproject;
py ecu_commit_test.py --confirm-write
```

The exact test transaction is:

```text
field 56 = target dropdown value
field 57 = 14 9F 3C 02 commit token
```

The Engine ECU web button remains disabled until this test succeeds.
