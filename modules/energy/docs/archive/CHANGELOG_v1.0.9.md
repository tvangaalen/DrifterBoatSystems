# Mastervolt Web App v1.0.9

- Shore Power and AC Loads frequency information now use the same green bullet, typography and status color as other tile state information.
- Replaced the Shore Power `INV` control with `SUP`, controlling the verified CombiMaster Btm3 field 11 named `AC IN support`, with write/readback verification.
- Marina mode now additionally enables the inverter, enables AC IN support and sets AC input limit to 15 A.
- Centered MASTERVOLT in the flexible header space between the hamburger icon and the System OK indicator.
- Updated application/footer version and PWA cache to v1.0.9.

Discovery evidence: CombiMaster Btm3 field 11 is writable, is named exactly `AC IN support`, uses an Eventable boolean-like 0/1 value, and read back as 1.0 during the read-only scan. Btm1 field 49 remains read-only `Supporting` status.
