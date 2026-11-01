# Mastervolt Web App v1.4.25

- Removed the wide All charge and All discharge buttons below the BMS matrix.
- Converted the remaining All charge and All discharge controls into state-aware ON/OFF toggles matching the individual battery controls.
- Queue feedback is shown only while a control request is actually waiting.
- Once execution starts, write verification and refresh continue silently in the background.
- Successful controls no longer show a completion pop-up; failures remain visible until acknowledged.
