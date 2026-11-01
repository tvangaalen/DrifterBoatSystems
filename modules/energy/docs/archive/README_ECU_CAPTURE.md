# Engine ECU write capture — v0.14.1

## What we now know

Read-side semantics are proven:

```text
INT Yanmar ECU
Field 56 — Power
0 = Off
1 = On
```

However, our generic Btm1 dropdown write:

```text
class 0x18
[field=56, tab=0, float value]
```

did not change the device. The field remained `1 = On`.

Therefore v0.14.1 disables the Engine ECU web write button again.

## Why USBPcap

The MasterBus USB Link is a HID device and generally cannot be opened
simultaneously by MasterAdjust and our Python application.

A normal Python HID sniffer would therefore not see MasterAdjust's write.

USBPcap captures the USB traffic below the HID application layer, allowing
MasterAdjust to own the device while the USB transactions are recorded.

## Capture procedure

First stop Uvicorn and close all Python MasterBus programs.

Optional: confirm the MasterBus USB device:

```powershell
cd C:\temp\mastervoltproject;
.\find_masterbus_usb.ps1
```

Start the guided capture:

```powershell
cd C:\temp\mastervoltproject;
.\ecu_capture_session.ps1
```

The script looks for `USBPcapCMD.exe` in common Wireshark/USBPcap locations.

When USBPcap asks for the output file use:

```text
C:\temp\mastervoltproject\captures\ecu_power_masteradjust.pcap
```

While capturing:

1. Open MasterAdjust.
2. Select `INT Yanmar ECU`.
3. Change `Power` ON -> OFF.
4. Wait about 3 seconds.
5. Change `Power` OFF -> ON.
6. Wait about 3 seconds.
7. Stop the USBPcap capture with `q`.

Then upload the `.pcap` file to ChatGPT.

## What we will compare

We will isolate USB HID OUT reports sent to:

```text
VID 1A64
PID 0000
MasterBus USB Link
```

and reconstruct their embedded MasterBus CAN frames.

We are specifically looking for whether MasterAdjust adds:

- an adjacent hidden-field commit write (for example field 57);
- an event/command token;
- a different CAN class/opcode;
- an extra transaction before/after field 56;
- or a write to a related field instead of field 56 itself.
