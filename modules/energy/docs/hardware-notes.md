# Hardware notes

Findings from the hardware-verification work (v0.11–v0.18) that are still relevant to the code. The field-by-field
measurement map is in [`../VERIFIED_FIELD_MAP.txt`](../VERIFIED_FIELD_MAP.txt) (written for v0.17); this file records
what changed afterwards and why. See [`../CHANGELOG.md`](../CHANGELOG.md) for the release history.

> **Rule of thumb:** MasterBus field numbers are never guessed. A field is used only after it was verified against
> live hardware, a device snapshot (`py -m tools.inspect_device snapshot`) or a MasterAdjust capture. The discovery code exists for
> diagnostics and is not run at normal start-up.

## Where the VERIFIED_FIELD_MAP.txt differs from the current code

| Topic | v0.17 map | Now |
|---|---|---|
| Solar tile voltage | field 4 (PV voltage) | **field 6** (battery/output voltage); field 4 kept as `panel_voltage` and shown as `PV ###V` (v0.18.5, v1.0.7) |
| Alternator current | derived, gated by shaft fields | derived from the house DC balance, gated by Alpha Pro **field 5** state (v0.18.10–11, see below) |
| Alternator load tile | – | Alpha Pro field 6 (battery voltage) × field 8 (field current); field 8 is field/excitation current, not output current (v1.0.7) |
| Inverter | – | added v1.0.11: CombiMaster fields 11/12 (V/A) gated by fields 47/49 |
| Total DC load | – | excludes AC loads (v1.0.8) |
| Storage SOC | MasterShunt field 0 | House SOC is the average of the DALY BMS SOCs (v1.3.16); Start/Bow still use MasterShunt field 0 |

## Controls

| Control | Device | Write | Notes |
|---|---|---|---|
| Inverter | CombiMaster `1B7CE1` | field 19 + commit 20 | |
| Charger House | CombiMaster | field 21 + commit 22 | |
| AC input limit | CombiMaster | field 23 | 3–15 A |
| AC IN support (`SUP`) | CombiMaster, **Btm3** | field 11 (writable 0/1) | write with read-back. Btm1 field 49 is the read-only *Supporting* status |
| Charger Start / Bow | Mass Charger `63D010` / `61CA96` | field 64, 0 = Standby / 1 = On | |
| Solar | SCM `31B483` | field 12 (0/1) + commit token on field 13 | OFF verified by read-back. ON is permissive: the SCM may fall straight back to OFF without PV (night), as MasterView does |
| Alternator OFF | Alpha Pro `329B8C` | field 39 (`Stop charge`) = 1 + commit 40 | verified against field 5 = 5 (*Stopped*) |
| Alternator ON | Alpha Pro | field 39 = 0 + commit 40 only | no Bulk request (field 33/34): the Alpha Pro is expected to resume charging by itself; success = field 5 reaches Bulk/Absorption/Float. Since v0.18.10; earlier versions sent Bulk (33 + 34) after clearing Stop charge |
| Engine ECU | Yanmar `3AE394` | **field 43** (`Mac/Magic On`), OFF 0.0 / ON 1.0, **no commit** | see below |
| Float (high-SOC policy) | CombiMaster 42/43, Solar 18/19, Alpha Pro 37/38 | command + commit | verified by charger state = Float |

Safety rules baked into the UI/code: Engine ECU OFF always needs an explicit confirmation (default action *Keep ECU ON*);
operating modes never switch the ECU off; every write that has a read-back is verified.

## Enumerations

| Device | Field | Values |
|---|---|---|
| CombiMaster | 1 (charger state) | 0 Off, 1 Bulk, 2 Absorption, 3 Float |
| Mass Charger | 1 (charger state) | 0 Off, 2 Bulk, 3 Absorption, 4 Float, 5 Constant voltage |
| Solar SCM | 3 (charge state) | 0 Off, 1 Bulk, 2 Absorption, 3 Float |
| Alpha Pro | 5 (charger state) | 0 Off, 1 Bulk, 2 Absorption, 3 Float, 5 Stopped |

Unknown values display as `Unknown (n)`.

## Engine ECU power (field 43)

The generic Btm1 dropdown write to field 56 (`Power`) did not change the ECU, even with a commit token on field 57.
A USBPcap capture of MasterAdjust showed the real operation:

```text
CAN ID 0x183AE394   ON -> OFF   2B 00 00 00 00 00   (field 43, float 0.0)
CAN ID 0x183AE394   OFF -> ON   2B 00 00 00 80 3F   (field 43, float 1.0)
```

MasterAdjust also continuously reads fields 38–41 and 43. No commit write was seen. Field 56 is configuration, not the
runtime power command.

An earlier start-up routine re-discovered field 56 and overwrote this mapping in the web server (fixed in v0.15.1),
which is why the mappings should always be checked before starting (`py -m tools.show_fields`):

```text
engine_ecu  verified True   address 3AE394   field 43   name "Mac/Magic On"   protocol btm1   type bool   commit_field None
```

### Repeating the capture

The MasterBus USB Link (VID `1A64`, PID `0000`) is a HID device that MasterAdjust and this app cannot share, so USB
traffic is captured below the HID layer with USBPcap:

1. Stop the web server and close every Python MasterBus tool.
2. Optional: `.\find_masterbus_usb.ps1` to confirm the device.
3. `.\ecu_capture_session.ps1` (finds `USBPcapCMD.exe` in the usual Wireshark/USBPcap locations); write the capture to `captures\ecu_power_masteradjust.pcap`.
4. In MasterAdjust select `INT Yanmar ECU`, switch Power ON → OFF, wait ~3 s, OFF → ON, wait ~3 s, then stop USBPcap with `q`.
5. Inspect the HID OUT reports sent to the USB Link and reconstruct their embedded MasterBus CAN frames.

## DC current model (alternator and Other DC loads)

The Alpha Pro has no trustworthy alternator output-current field (field 21 is *Battery current* and must not be used).
Alternator current and *Other DC Loads* cannot both be solved from a single MasterShunt equation, so a baseline is
learned while the alternator is not charging.

Sign convention: House MasterShunt current is **positive into** the battery (charging), negative out of it.

```text
Alpha state Off (0) or Stopped (5):
  TotalHouseLoad_A = ChargerHouse_A + Solar_A - HouseBattery_A       # low-pass filtered, alpha 0.25 -> baseline
  OtherDC_A        = max(0, TotalHouseLoad_A - ChargerStart_A - ChargerBow_A - EngineECU_A)

Alpha state Bulk / Absorption / Float (1/2/3):
  Alternator_A     = max(0, HouseBattery_A + TotalHouseLoadBaseline_A - ChargerHouse_A - Solar_A)
  OtherDC_A        = max(0, TotalHouseLoadBaseline_A - ChargerStart_A - ChargerBow_A - EngineECU_A)

Alternator W = Alpha field 14 (alternator voltage) x Alternator_A
```

Shaft rotation (fields 11/12) is exposed as `shaft_running` for diagnostics only. When stopped, alternator A/W are
reported as exactly 0. Known DC loads (Charger Start, Charger Bow, Engine ECU, Inverter, Alternator field current) are
subtracted from *Other DC Loads* so nothing is counted twice.

**Engine ECU input current** is estimated because no input-current field exists: `Pout = Vout x Iout` (fields 40/41),
`Pin = Pout / 0.85`, `Iin = Pin / Vin` (field 39). 85% is a deliberately conservative efficiency for its very low
operating point.

## Float protection (cell-voltage trigger)

Runs server-side every 3 s, independent of any browser. Active Charger House, Solar and Alternator charging is forced
to Float and verified (20 s retry cooldown) as soon as the highest single cell voltage of any of the three batteries
reaches *Switch to Float when any cell reaches* (default 3500 mV, settings `float_cell_trigger_mv`). It switches back
to Bulk only once every cell is at or below *Switch to Bulk once every cell is at or below* (default 3420 mV,
`float_cell_resume_mv`, at least 30 mV below the trigger). Inactive sources are never switched on. Status is in
`/api/energy` as `high_soc_float_policy`, which names the active condition via `trigger` (`"cell_voltage"` or
`"held"`).

The cell-voltage trigger was added in 1.13.0 after 10 days of stored history showed 44 cell-voltage/imbalance alarm
episodes (several ending in the BMS itself cutting the charge MOSFET) while the average House SOC was as low as
58-91% - three parallel batteries do not necessarily reach a high SOC together, and one battery's own coulomb-counted
SOC can already read 100%, with one of its cells already inside DALY's own high-voltage alarm band (observed starting
around 3550-3600 mV; a normal full-charge cell sits around 3360-3390 mV), while the pack average was nowhere near the
95% the SOC trigger used to sit at. **1.17.0 removed the SOC trigger entirely**: Float protection now reacts only to
cell voltage. No DALY alarm-threshold registers are read or changed; 3500 mV is the app's own, independently-chosen
figure.

Only *fresh* cell readings count (`mastervolt/soc.py`, `cell_voltage_stats()`): each battery's reading must be younger
than max(120 s, 4 x the BMS refresh interval); if none is fresh, the highest cell voltage is unknown. While Float is
latched and the cell reading is unknown the policy *holds*: sources that (re)start charging are still forced to
Float, and Bulk is never resumed on old data (`soc_source` = `stale_hold`, `max_cell_mv`, `max_cell_battery`). An
unknown cell voltage never starts Float protection by itself. The **cell spread** (worst cell-to-cell difference
within a battery, `max_spread_mv`/`max_spread_battery`) is reported for the same reason but is deliberately
informational only - not wired into the trigger, so a brief, harmless imbalance mid-charge cannot stall normal Bulk
charging. The DALY-average House SOC (`soc.house_soc()`) is still computed and shown on the Control panel and in
`/api/energy` for information (`soc_fresh_batteries`, `soc_age_seconds`, `last_known_soc`), but no longer affects
Float protection at all. There is deliberately no MasterShunt fallback (see above).

## DALY BMS / balancer notes

- **BMS** (`BATTERY 1`–`3`): legacy `0xA5` protocol. Writes use source byte `0x80`; SOC `0x21` (value x10), Charge MOS `0xDA`, Discharge MOS `0xD9`. Firmware variants differ on whether payload `1` means ON, so the encoding is learned per battery and per MOS by read-back and stored in `data/bms_mos_encoding.json`. Protection-threshold registers are deliberately not accessed. Alarm bits come from `0x98`; balancing bit 0 = cell 1.
- **Balancers** (`DL-BAL1`–`3`): monitored directly over their own FFF1 characteristic, read-only. Balance current is the current byte of response `0x93` at 0.01 A/LSB; the `0x90` pack current is unrelated.
- **Bluetooth coordination:** one Windows machine cannot hold six reliable GATT sessions, so a single priority queue arbitrates the radio: user controls > manual BMS refresh/reconnect > automatic reconnect > automatic BMS reads > balancer traffic. BMS links are persistent (one thread + event loop each); balancers connect, read and disconnect one at a time once all BMS links are stable.
- **Bluetooth robustness (1.12):** every Windows BLE call has a hard deadline (`asyncio.wait_for`), a half-open client is always disconnected, and coordinator leases carry a token and a maximum hold time so a hung call can never keep the radio. A balancer that keeps failing backs off exponentially (retry x 2^n, at most 5 min) without slowing the others; a stall watchdog forces a rescan, then rebuilds the balancer worker, and flags it as *wedged*. A balancer or BMS status is published only when all nine DALY commands were answered, and unanswered commands are asked once more. With one BMS unreachable for 2 minutes the balancers are allowed again (*degraded* mode). Events, per-device counters and timings: `logs/bluetooth.log` and `GET /api/bluetooth-events` (`counters.<device>.timings.<connect|notify|read|disconnect|radio_wait|radio_hold|scan>` with count, average, median, p95 and maxima of successful and failed attempts; use these, not guesses, to choose time-outs). `counters.<device>.signal` holds the advertisement signal strength (RSSI, dBm: last, average, recent average, min, max) of every DALY device seen in a scan; the balancer scan log line also lists the signal of each device and of balancers that were visible but not looked for. Roughly, -50 to -70 dBm is a good link, below about -85 dBm is marginal. Background: in the analysed history the balancers were silent 29% of the time, every gap ending at a server restart; Battery 2's link was lost 4.3% of the time against 0.3% for Battery 1 and 3.
- **Voltage-derived SOC** (*SOC - Charging* / *SOC - Discharging*) interpolates the average cell voltage against LiFePO4 reference curves. These are comparison indicators; `Set SOC - charge/discharge` writes the same values to the BMS. A manual percentage can also be written directly (`set_soc_value`, `POST /api/bms/{id}/set-soc-value` or `/api/bms/set-all-soc/value`, body `{"percent": N}`), using the same `0x21` register (value x10).

## Utility scripts

Tools run from the project folder as `py -m tools.<name>` (the web server must be stopped first: it holds the USB Link and the
Bluetooth radio). Tools marked **writes** change device state and require an explicit confirmation flag. The tests are listed in
[`MANUAL.md`](MANUAL.md#92-tests).

| Tool | Purpose |
|---|---|
| `tools.show_fields` | Print the fields the application polls and the active control mappings, taken from the code (check `engine_ecu` before starting). No hardware access |
| `tools.inspect_device snapshot --device <addr>` | Read-only field snapshot of a device: protocol, type, writability and value of every field (uses the known `max_index`; `--max-index N` overrides). Also `candidates` (on/off-looking writable fields of the Mass Chargers and the ECU), `writable` (Solar and Alpha Pro writable fields and dropdown options) and `controls` (the fields around the verified controls) |
| `tools.alpha_stop_charge_watch` | Watch Alpha Pro Stop-charge changes made in MasterView (read-only) |
| `tools.capture_hid [--seconds N]` | Print the raw HID input reports of the USB Link (read-only; for a capture of MasterAdjust use USBPcap, below) |
| `tools.reversible_write_test <device> --confirm-write` | **writes** - switch a Mass Charger, the ECU (field 43) or Solar to the opposite state with the verified control code, verify, restore |
| `tools.cache_product_images [--force]` | Download the tile product photos into `static/products/` |
| `tools.build_manual` | Build `docs/manual.html` from `docs/MANUAL.md` |
| `python -m mastervolt.reports.battery_health` | Read-only battery health report from the stored history (verdict per battery, cell resistance, current sharing, alarms, balancers); `--split` compares before/after a change; also available in the app under History → Reports |
| `tools\find_masterbus_usb.ps1`, `tools\ecu_capture_session.ps1` | USB Link detection and guided USBPcap capture |

The experiments with the ECU's field 56 (`ecu_control_test`, `ecu_commit_test`, `ecu_dropdown_probe`, `ecu_power_probe`) and the
v0.x discovery tools were removed in 2.0.0; they stay in the Git history (tag `v1.22.2`).
