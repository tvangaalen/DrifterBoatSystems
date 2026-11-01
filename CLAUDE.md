# Drifter Boat Systems

One web app (iPhone/iPad PWA) for four existing boat servers: MasterVolt YMS (`../MasterVolt-YMS`), the Orca Core 2
anchor watch (`../OrcaCore2`), BoatGuard (`../BoatGuard`) and the VIOMI controller (`../viomi-w1-controller`).
`drifter.py` is a stdlib gateway that serves `web/` and passes requests on. Overview: `README.md`.

## Hard rules

- **The module servers stay the authority.** Never move logic into the gateway or the page: Float protection, the anchor alarm (`AnchorWatch.tick`), arming and the washer schedule run on their own servers. The gateway only passes requests on; it never sends a command by itself, retries a command or polls hardware.
- **Each module project's own CLAUDE.md rules still apply** to what this app sends (no guessed MasterBus fields, read-only on the Orca Core, ECU safety, etc.). Read the relevant one before adding a control.
- **Engine ECU OFF** always needs the confirmation whose default is *Keep ECU ON* (`energy.js`); Escape/tap outside = keep on. Never weaken this or add a path that switches the ECU off without it.
- Confirm-first for every action that cuts power, stops charging, stops a watch or deletes data; the safe answer is the default button.
- **Route allowlist**: a new upstream route goes into `ROUTES` in `drifter.py` with the narrowest pattern, plus a test in `tests/test_gateway.py`. Do not add catch-all patterns. SOC calibration (`set-soc-*`), history export and the CA download are deliberately not exposed.
- Keep the gateway checks: `check_bind` (localhost/private only), `host_allowed` (DNS rebinding), and for POST: JSON, `X-Drifter-Request: 1`, same Origin. The washer's `X-Viomi-Request` header is added by the gateway only after those checks.
- **Never run UI tests against the live servers.** Use `py tools/mock_upstreams.py --gateway` (launch config `drifter-mock`, port 8101). A test click on the live servers can arm the camera, switch the inverter or start the washer. GETs to live servers for reading payload shapes are fine.
- Do not start, stop or restart the live module servers from here (MasterVolt owns the USB link and Bluetooth; restarts pause Float protection and the anchor watch).
- LAN only: never bind a public address, port-forward or tunnel. Remote access is UniFi Teleport (clients 192.168.2.x).
- HTTPS certificates come from the existing Mastervolt Local CA (`setup_https.ps1` only reads the CA folder). Never create a new CA or write into the CA folder.
- Times are always 24-hour (`hm`/`hms`/`dayTime` in `app.js`); never locale time defaults.
- Live data is never cached by the service worker (`/api/` is skipped). Bump `CACHE` in `web/sw.js` with every release so home-screen apps update.
- Never commit `config.json`, `certs/` or `logs/`.

## Conventions

- Python 3.12+, stdlib only, Windows, `py` launcher. Dense style like the sibling projects.
- Frontend: plain JS, no build step. `app.css` holds all colours as tokens per theme (light, dark, night, auto = device); modules never hard-code colours. New UI uses the existing components (`card`, `row`, `stats`, `hero`, `badge`, `btn`, `switch`, `seg`, `field`, `sheet`).
- A module registers with `Drifter.register({id, title, short, icon, every, background, load, render, mount, tile, badge})`; commands go through `Drifter.api(module, path, body)` and `Drifter.run(...)`, confirmations through `Drifter.confirm(...)`.
- Check new layouts at 390 px (iPhone), 820 px portrait and 1180 px landscape (iPad), in light, dark and night.

## Verifying

```powershell
py tests/test_gateway.py      # gateway: allowlist, host/origin/CSRF checks, passing on (fake upstreams)
node --check static\app.js    # and the other static\*.js files
```

Then the UI against the mocks (`drifter-mock`). Delete `__pycache__` afterwards.

## Releasing

Bump `VERSION` in `drifter.py`, `CACHE` in `web/sw.js`, the version line in `README.md`, and add a `CHANGELOG.md` entry.
