# Mastervolt project v0.15.1

## Important Engine ECU web-control fix

The command-line test for Engine ECU field 43 worked, but the web button did not.

The cause was found in the web-server startup path.

An older v0.13 feature still ran this logic whenever Uvicorn started:

```text
rediscover Yanmar field 56 "Power"
overwrite control_maps["engine_ecu"]
```

Therefore:

- `ecu_field43_test.py` used the correct verified field 43 mapping and worked;
- the web server subsequently overwrote that mapping with field 56;
- the iPhone button then tried the old field-56 write, which we already proved
  does not control the ECU.

v0.15.1 removes that startup overwrite.

The Engine ECU web control now remains permanently mapped to the captured and
hardware-verified MasterAdjust transaction:

```text
INT Yanmar ECU
address 3AE394
field 43 "Mac/Magic On"

OFF = 0.0
ON  = 1.0
no commit field
```

## Verify the mapping before starting

```powershell
cd C:\temp\mastervoltproject;
py show_control_maps.py
```

For `engine_ecu` it must show:

```text
verified     : True
address      : 3AE394
field        : 43
name         : Mac/Magic On
protocol     : btm1
type         : bool
commit_field : None
```

## Start server

```powershell
cd C:\temp\mastervoltproject;
py -m uvicorn app:app --host 0.0.0.0 --port 8000
```

If the iPhone has the old PWA cached, close/reopen the Home Screen app or reload
once in Safari.


## Field audit utility

v0.15.3 adds a dashboard field audit tool that prints the exact field numbers
currently used by the application, including persisted dynamic mappings from
`device_maps.json`.

Run:

```powershell
cd C:\temp\mastervoltproject;
py field_audit.py
```

Paste the complete output into ChatGPT if you want to verify or correct any
mapping.
