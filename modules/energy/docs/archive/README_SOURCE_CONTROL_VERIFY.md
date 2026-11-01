# Source control verification utility

`source_control_verify.py` supports two steps:

1. Read-only inspection of every writable field and dropdown option on:
   - SCM Solar [31B483]
   - APR Alpha Pro MB [329B8C]

2. A reversible Solar field-12 ON/OFF test. The write test is only performed
   with `--confirm-write` and restores the original value automatically.

The Alpha Pro is intentionally inspection-only until its exact ON/OFF field and
semantics are identified from MasterBus metadata. No candidate write is guessed.
