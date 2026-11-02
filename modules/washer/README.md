# VIOMI W1 controller

Lokale controller voor de VIOMI W1 (`viomi.washer.w1`), versie `4.0.0`: de API achter de module **Washer** van de Drifter-app (status, bediening, diagnostiek en een planner op de server). Sinds 3.8 heeft de controller geen eigen webpagina; de bediening zit in Drifter.

Onderdeel van [DrifterBoatSystems](https://github.com/tvangaalen/DrifterBoatSystems) (`modules/washer`); de oude repository viomi-w1-controller is gearchiveerd.

## Opbouw (4.0)

Een Python-package op FastAPI, volgens Drifters modulecontract (`common/service.py`):

| Bestand | Inhoud |
|---|---|
| `washer/config.py` | `viomi_config.json`, gecontroleerd tegen een schema (`WasherConfig`) |
| `washer/device.py` | de wasmachine via MIoT (`python-miio`): eigenschappen, acties, programma's en toestanden |
| `washer/events.py` | het gebeurtenissenlog en de toestandswissels van de wasmachine |
| `washer/schedule.py` | de planner: starten of klaar zijn op een tijdstip, gevolgd tot het programma klaar is |
| `washer/diagnostics.py` | de opstartcontroles |
| `washer/api.py` | de HTTP-API |

De API geeft dezelfde antwoorden, statuscodes en meldingen als de Flask-controller 3.8: `test_api_contract.py` legt dat vast en draaide tegen beide versies.

## Draaien

Op de boot start de Drifter-service (`drifterd`) de controller: `.venv\Scripts\python.exe -m washer` in deze map, met de configuratie in `C:\DrifterData\washer`. De omgeving komt uit Drifters `uv.lock` (`py -3.12 tools\sync_envs.py washer`). `python-miio` 0.5.12 vraagt om `netifaces`, dat op Windows voor Python 3.12 een C-compiler nodig heeft; de controller gebruikt het niet, dus de lockfile laat het weg.

- Gewoon HTTP op `127.0.0.1:8080` (`WASHER_BIND` mag een ander privé-adres noemen, nooit een publiek adres of alle interfaces).
- Elk verzoek behalve `GET /health` moet de header `X-Drifter-Token` dragen met het token dat drifterd bij elke start maakt en aan de gateway en de modules meegeeft (`DRIFTER_TOKEN`). Zonder token weigert de controller alles behalve `/health`. Een webpagina kan het token niet kennen, dus andere websites en DNS-rebinding bereiken de wasmachine niet; de gateway doet zijn eigen controles voor de app.
- `viomi_config.json`: `washer_ip` (het lokale adres van de wasmachine; het voorbeeldadres `192.0.2.10` is een documentatieadres), `token` (het MIoT-token van 32 hexadecimale tekens), optioneel `expected_pc_ip`. `VIOMI_IP` en `VIOMI_TOKEN` in de omgeving gaan voor. Een fout in het bestand is niet fataal: de diagnostiek meldt het.

API: `GET /health`, `/api/status`, `/api/schedule`, `/api/start-check`, `/api/diagnostics` (`?recheck=1` voert de opstartcontroles opnieuw uit) en `/diagnostics/export` (JSON, zonder token); `POST /api/power/on|off`, `/api/start`, `/api/pause`, `/api/program|temperature|rinses|spin/<waarde>`, `/api/schedule`, `/api/schedule/cancel`.

De planner bewaart zijn status in `viomi_schedule.json` (overleeft een herstart). Houd de controller actief voor geplande programma's; drifterd doet dat.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest test_washer
```

Met een nep-wasmachine en een vaste klok: er wordt niets naar een echte wasmachine gestuurd.

## Configuratie en privacy

Commit uitsluitend broncode, documentatie en fictieve voorbeelden. `.gitignore` sluit lokale configuratie, tokens, logs, diagnostische JSON en runtime-status uit; de privacyscan van de repository controleert elke commit.

## Herkomst

Uitgangspunt was `viomi_web_english_v57.py` uit de ChatGPT-chat **V48 Creation Request**, aangeleverd door de eigenaar. 3.7-v58 voegde bescherming tegen andere websites toe, 3.8 verving de eigen pagina's door de Drifter-app, 3.8-v60 gebruikte Drifters gedeelde controles, en 4.0 is dezelfde controller als package op FastAPI met het modulecontract. Bediening, validatie en planner zijn in al die stappen gelijk gebleven.
