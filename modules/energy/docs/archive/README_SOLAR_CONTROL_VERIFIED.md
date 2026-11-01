# v0.17.7 — Solar ON/OFF control verified

SCM Solar field 12 (`On/Off`) is now enabled for the Solar tile.

Important behavior:
- The field is a controller ON/OFF request.
- With insufficient PV input (for example at night), the controller can immediately
  return the field to OFF after an ON request.
- This matches the behavior observed in MasterView, so the immediate OFF readback
  is not treated as a failed command.

Alpha Pro remains disabled until its `Stop charge` semantics are captured.
Use `alpha_stop_charge_watch.py` while changing Stop charge in MasterView.
