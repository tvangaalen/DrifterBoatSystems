# VIOMI W1 webcontroller

Lokale Flask-webcontroller voor de VIOMI W1 (`viomi.washer.w1`), versie `3.7-v58`. Inclusief status, bediening, diagnostiek en een server-side scheduler.

Repository: https://github.com/tvangaalen/viomi-w1-controller (publiek).

## Installatie op Windows

Gebruik een lokale Python-installatie, versie 3.12 of 3.13. De installatie en de webinterface zijn op Windows met beide versies getest zonder wasmachine; de werking met de wasmachine is hier niet getest. Python 3.14 is niet getest.

Voer in PowerShell vanuit deze projectmap uit:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements-miio.txt
Copy-Item viomi_config.example.json viomi_config.json
```

Alle afhankelijkheden staan op vaste versies. `python-miio` 0.5.12 vereist `netifaces`, dat op Windows voor Python 3.12 en nieuwer alleen met een C-compiler te bouwen is. De controller gebruikt `netifaces` niet (alleen de firmware-updater van `python-miio` doet dat). Daarom worden `python-miio` en `micloud` met de tweede `pip`-opdracht zonder afhankelijkheden geïnstalleerd; hun overige afhankelijkheden staan in `requirements.txt`. `pip check` meldt daardoor dat `netifaces` ontbreekt; dat is verwacht.

Vul in `viomi_config.json` het lokale IP-adres van je wasmachine en je eigen MIoT-token van 32 hexadecimale tekens in. Het voorbeeldadres `192.0.2.10` is een documentatieadres en moet worden vervangen. `expected_pc_ip` is optioneel; laat dit op `null` of vul het verwachte lokale IP-adres van de computer in.

`VIOMI_IP` en `VIOMI_TOKEN` kunnen als omgevingsvariabelen worden gebruikt en gaan voor de waarden in het configuratiebestand. Het programma laadt geen `.env`-bestand automatisch.

## Starten

```powershell
.\.venv\Scripts\python.exe viomi_web_english_v58.py
```

Open http://127.0.0.1:8080 op dezelfde computer. Een ander apparaat in hetzelfde vertrouwde netwerk kan de interface via het lokale IP-adres van de computer op poort 8080 openen. De server luistert op alle netwerkinterfaces en bevat geen aanmeldbeveiliging: stel deze poort niet open naar internet.

Websites die je in een browser in hetzelfde netwerk opent, kunnen de wasmachine niet bedienen: elke POST moet de header `X-Viomi-Request` bevatten die alleen de eigen pagina meestuurt, en verzoeken met een afwijkende `Origin` worden geweigerd. Daarnaast accepteert de server alleen verzoeken waarvan de `Host` een IP-adres, `localhost` of de eigen computernaam (ook met `.local`) is; dat blokkeert DNS-rebinding. Gebruik je een andere naam, zet die dan in `allowed_hosts` in `viomi_config.json`, bijvoorbeeld `"allowed_hosts": ["wasmachine.lan"]`. Geweigerde verzoeken verschijnen als `BLOCKED` in het gebeurtenissenlog. Dit vervangt geen aanmeldbeveiliging.

Houd het programma en de computer actief voor geplande programma's. De scheduler bewaart zijn lokale status in `viomi_schedule.json` naast de bron. Loggebeurtenissen worden in het geheugen bijgehouden; gedownloade diagnostiek kan lokale netwerkgegevens bevatten.

## Configuratie en privacy

Commit uitsluitend broncode, documentatie en fictieve voorbeelden. `.gitignore` sluit lokale configuratie, tokens, logs, diagnostische JSON, runtime-state en virtuele omgevingen uit. De voorbeeldconfiguratie is expliciet toegestaan. Controleer nieuwe bestanden en bronwijzigingen voor iedere push op geheimen; uitsluitingen controleren geen broninhoud en verwijderen geen eerder gecommitteerde bestanden.

## Herkomst en validatie

Uitgangspunt is `viomi_web_english_v57.py` uit de ChatGPT-chat **V48 Creation Request**, aangeleverd door de eigenaar. Voor publicatie is uitsluitend het standaard lokale wasmachineadres vervangen door `192.0.2.10`; de bediening en schedulerlogica zijn behouden.

Versie `3.7-v58` voegt alleen de bescherming tegen verzoeken van andere websites toe (CSRF en DNS-rebinding); bediening en schedulerlogica zijn ongewijzigd.

De bron is op syntax en ingebouwde geheimen gecontroleerd. Er is geen verbinding met de wasmachine gemaakt en er zijn geen opdrachten aan de wasmachine verzonden.
