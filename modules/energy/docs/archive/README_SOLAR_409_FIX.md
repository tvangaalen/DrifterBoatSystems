# v0.17.9 — Solar control 409 fix

Problem:
`POST /api/control/device/solar` returned HTTP 409 when an ON request was sent
at night. The generic control path required the field to remain at the requested
value. SCM Solar field 12 can immediately return to OFF with insufficient PV,
which is also the behavior observed in MasterView.

Fix:
- Solar now uses a dedicated `set_solar_enabled()` path.
- It sends field 12 as the verified On/Off request.
- It reads field 12 back for status/reporting.
- It does NOT treat immediate OFF readback after an ON request as a failed write.
- Other verified controls keep their stricter readback verification.

No measurement mappings were changed.
