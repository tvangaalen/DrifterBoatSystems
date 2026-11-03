# Drifter — user manual

Drifter is one app for the boat's systems: the energy system (Mastervolt and the DALY batteries), the anchor watch,
BoatGuard (the camera) and the washing machine. It runs on the boat PC; you use it on the iPhone, the iPad or any browser on
the boat network, and away from the boat through UniFi Teleport.

Each system keeps working on its own when the app is closed: Float protection, the anchor alarm and its push alerts,
arming the camera and the washer's schedule all run on the boat PC. The app shows them and sends your commands.

All times are on the 24-hour clock.

## 1. Getting started

- **Open the app:** in Safari, https://192.168.1.166:8100/ (on the boat Wi-Fi, or with UniFi Teleport switched on).
- **Install it:** Share → *Add to Home Screen*. It then opens full screen like an app. After an update, close it completely
  and open it again to load the new version.
- **A new phone or tablet** must trust the boat's own certificate once; see the runbook (section 7) or ask whoever looks
  after the boat PC.
- **Layout:** on the iPhone a tab bar at the bottom (Overview, Energy, Anchor, Guard, Washer); on the iPad a side bar (an
  icon rail in portrait). The gear button at the top opens the System page; the sun/moon button the display settings.
- **Not reachable:** when a system does not answer, its page says so in a red card and keeps showing the last values
  with their time; its tile on the Overview says *offline*. It comes back by itself.

## 2. Overview

One tile per system with its key values. Tap a tile to open its page. A badge in the tile and a dot in the navigation
show what needs attention: *alarm* (red) or *check* (orange).

- **Energy:** the house bank's charge on a meter (red empty, green full), the battery power, its voltage and current, and
  the four flows: Charger, Alternator, Solar and the
  DC load (shown with a minus sign: it is taken from the battery).
- **Anchor watch:** whether the anchor is set and, if so, the distance to it; depth, wind and the GPS state.
- **BoatGuard:** whether you are on board and whether monitoring is on; phone, camera and its battery.
- **Washer:** on/off, the program and its settings, and the time it will be ready.

## 3. Alarms

When the anchor watch reports an alarm, a **red bar** appears at the top of every page with the reason. *Silence 5 min*
mutes it for five minutes (the alarm stays until the cause is gone); while silenced the bar says until when, and its
button opens the anchor page. With **Sound on** (button in the bar and on the anchor page) the phone or tablet sounds and
vibrates during an alarm and keeps its screen awake. Push alerts (Pushover) reach the phone even when the app is closed.

If the anchor is set and the anchor watch cannot be reached, the bar says *Anchor watch not reachable*: check the Wi-Fi
and the boat PC.

## 4. Energy

Four views at the top of the page. The full description of every value and of how it is measured is in the energy
manual: History → *Open the manual*.

- **Control:** the house bank (charge on a meter, power, voltage, current, temperature, Float/Bulk state), the energy providers (shore, charger, alternator, solar; total DC in at the top) and the energy consumers
  (with a minus sign, as they take power; total DC out at the top).
  - **Modes** switch several devices at once: *Motor*, *Anchor*, *Marina*, *Sail*; the active mode is marked until a
    single control changes. A mode never switches the Engine ECU off.
  - **Switches** sit on their own line: the charger, alternator and solar under the providers; the inverter, the start
    and bow chargers and the Engine ECU under the consumers (a greyed-out switch is not verified on the boat yet). AC
    support and the AC input limit are in the CombiMaster card. A switch keeps showing the real state until the system
    has read the new state back.
  - **Engine ECU off** always asks first, with *Keep ECU ON* as the default: switching it off stops a running engine.
    *Alternator off* asks too (*Keep Alternator ON*).
- **Batteries:** at the top an overview that fits one iPhone screen: the start and bow batteries with their meters,
  then the *House bank* frame with a tile per pack: its meter, voltage, current, temperature, cells (highest orange,
  lowest blue), the average cell voltage, the spread, when it was last read, its balancer, the ON/OFF switches for the
  charge (C) and discharge (D) MOSFETs and *Set SOC*. Below: the buttons for all packs; *Pack details*, one table with a
  column per pack (read time, SOC, Ah left, voltage, current, temperature, cycles, each cell, the average cell voltage and the
  maximum cell difference) and a *House* column (house SOC and voltage, the sums, the hottest pack, average and difference
  over all cells); the balancers (folded: tap to open);
  Bluetooth diagnostics and recent Bluetooth events. Every action that could cut power asks first, the safe choice being
  the default.
- **History:** charts of the state of charge, sources, DC consumers, battery current and cell spread for 6 hours up to 31
  days (touch a chart for the values at that moment), and the energy per period. Also the battery health report, the
  energy manual and the state of the history database.
- **Settings:** Float protection thresholds, the default AC limit, refresh intervals and how long history is kept. A
  shorter history asks first: older data is deleted.

**Float protection** runs on the boat PC: when one battery cell reaches the trigger voltage the chargers go to Float and
return to Bulk by themselves later. The app only shows its state.

## 5. Anchor watch

Four views: **Watch**, **Map**, **GPS & links** and **Settings**.

- **Drop the anchor:** *Dropping now* (the anchor is where the bow is now) or *Already lying to it* (the boat is already
  lying to the anchor), then choose the alarm radius; a scope calculator helps with the rode. **Move anchor** (tap the map
  or nudge 1 m), change the radius by ±5 m, and **Anchor up?** stops the watch (asks first).
- **Watch:** distance to the anchor and its maximum, depth, wind, AIS targets, speed, heading, the sun, the position
  (choose its format in Settings), and the tide over the next hours with chain advice and keel clearance.
- **Map:** street map, satellite (*Sat*) or *Plain*, with *Seamarks*; the boat, the anchor circle, the maximum swing, the
  rode, a fading track and AIS targets. *Start new track* clears the track (asks first). The Windy button opens the
  forecast for the boat's position.
- **Alarms:** anchor drag (the only emergency alert), GPS lost, no data from the Orca Core, an AIS target too close,
  shallow water and the wind limit. A drag alarm is only raised from a trustworthy position: a GPS that stops changing is
  not used.
- **GPS & links:** the GPS sources in order of preference (move one up or down, *Default order*); network GPS from a phone
  (GPS2IP, port 10110); the Orca Core; push alerts (Pushover, *Send test*), the still-alive check (*Ping now*), internet
  AIS (*Reconnect*) and noforeignland.com tracking (*Send now*). *GPS hold* means the Core holds a still position.
- **Settings:** the alarm limits, the boat (bow height, anchor ahead of the bow, My MMSI), the minimum chain formula and
  the position format; *Save settings*.

## 6. BoatGuard

BoatGuard arms the EZVIZ camera when your iPhone leaves the boat's Wi-Fi, and disarms it when you are back.

- The status shows whether you are on board, whether **Monitoring** is on, and the phone, camera and router. *Switch
  monitoring off?* asks first: the camera is then no longer armed automatically.
- **Test camera** arms and disarms it once. **Arming delay** and **Router check interval** set how quickly it reacts.
- Per notification (armed, disarmed, left the boat with monitoring off) its sound and priority, each with a test;
  *Send an emergency test?* asks first.
- **Log:** what BoatGuard did and when.

## 7. Washer

From top to bottom:
- **Status** with the time left and when it will be ready, and the **ON/OFF** power switch at its right (not during a
  wash; with a schedule set, switching off asks first).
- **Select program:** program, temperature, spin and rinses; *Set program* applies them, and the app says *applied* only after
  the washer has confirmed them; until then *Start now* and *Schedule* are greyed out.
- **Current program:** what the washer is set to now (program, temperature, time left, spin), with **Start now**,
  **Pause** and resume.
- **Schedule:** start at a time, or finish at a time; the controller on the boat PC starts it, also when the app is
  closed. A scheduled start can be cancelled.
- **Diagnostics:** one line with the state (green *Ready* when all is well); tap it to unfold the start-up checks, the
  controller's version, the washer's address, model and firmware, *Read now*, *Recheck* and an export.
- **Events:** one line with how many there are and the last one's time (orange when one failed); tap it for the list.

## 8. System

- **Display:** Auto (follows the device), Light, Dark and Night (dim red on black, keeps your night vision). Remembered
  on each device. Map tiles are dimmed in Dark and tinted red in Night.
- **Systems:** per system whether it is connected, whether its server runs (and for how long), and its last event.
  *Show log* opens its log; *Restart* restarts one after a confirmation that says what pauses. A restart is refused while
  a battery control runs or Float is latched (energy) or while the anchor watch has an alarm.
- **Drifter:** the app's own server and the Drifter service, with their logs.
- **Alerts:** a push message on your phone when a system has been down for 5 minutes, and when it is back. *Send test* checks
  that it arrives; *Not set up* means the boat PC has no Pushover keys for it yet (see the runbook).
- **Keys and tokens:** *Backup keys and tokens* copies the keys that cannot be made again without the services
  (Pushover, noforeignland.com, EZVIZ, the washer's token) to `C:\DrifterBackups` on the boat PC, replacing the previous
  copy, and says when it last did. Press it after one of them changed; nothing is copied unless you press it.
- **Supervisor events:** starts, restarts and stops.
- **Switch all systems off:** stops every system's server and the app's server on the boat PC, after a confirmation (the
  default is *Leave on*) that lists what stops, for example that the anchor alarm stops while the anchor is set. Switches,
  chargers and the camera stay as they are. It is refused while a battery control runs or the anchor watch has an alarm.
  Start everything again with the **Drifter Boat Systems** icon on the boat PC's desktop.

## 9. Safety at a glance

- Everything that cuts power, stops charging, stops a watch or deletes data asks first, and the safe answer is the
  default button; Escape or tapping outside the question also chooses it.
- The Engine ECU is never switched off without the *Keep ECU ON* question, and never by a mode.
- The app has no login: anyone on the boat network or on Teleport can use it. It is never reachable from the internet.
