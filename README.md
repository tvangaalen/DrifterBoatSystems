# VIOMI W1 webcontroller

Lokale Flask-webcontroller voor de VIOMI W1 (`viomi.washer.w1`), versie `3.7-v57`. Inclusief status, bediening, diagnostiek en een server-side scheduler.

Repository: https://github.com/tvangaalen/viomi-w1-controller (publiek).

## Installatie op Windows

Gebruik een lokale Python-installatie. De bron is syntactisch gecontroleerd met Python 3.12. Werking met de wasmachine en compatibiliteit met nieuwere Python-versies zijn hier niet getest. Afhankelijkheden zijn nog niet op vaste versies vastgezet.

Voer in PowerShell vanuit deze projectmap uit:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item viomi_config.example.json viomi_config.json
```

Vul in `viomi_config.json` het lokale IP-adres van je wasmachine en je eigen MIoT-token van 32 hexadecimale tekens in. Het voorbeeldadres `192.0.2.10` is een documentatieadres en moet worden vervangen. `expected_pc_ip` is optioneel; laat dit op `null` of vul het verwachte lokale IP-adres van de computer in.

`VIOMI_IP` en `VIOMI_TOKEN` kunnen als omgevingsvariabelen worden gebruikt en gaan voor de waarden in het configuratiebestand. Het programma laadt geen `.env`-bestand automatisch.

## Starten

```powershell
.\.venv\Scripts\python.exe viomi_web_english_v57.py
```

Open http://127.0.0.1:8080 op dezelfde computer. Een ander apparaat in hetzelfde vertrouwde netwerk kan de interface via het lokale IP-adres van de computer op poort 8080 openen. De server luistert op alle netwerkinterfaces en bevat geen aanmeldbeveiliging: stel deze poort niet open naar internet.

Houd het programma en de computer actief voor geplande programma's. De scheduler bewaart zijn lokale status in `viomi_schedule.json` naast de bron. Loggebeurtenissen worden in het geheugen bijgehouden; gedownloade diagnostiek kan lokale netwerkgegevens bevatten.

## Configuratie en privacy

Commit uitsluitend broncode, documentatie en fictieve voorbeelden. `.gitignore` sluit lokale configuratie, tokens, logs, diagnostische JSON, runtime-state en virtuele omgevingen uit. De voorbeeldconfiguratie is expliciet toegestaan. Controleer nieuwe bestanden en bronwijzigingen voor iedere push op geheimen; uitsluitingen controleren geen broninhoud en verwijderen geen eerder gecommitteerde bestanden.

## Herkomst en validatie

Uitgangspunt is `viomi_web_english_v57.py` uit de ChatGPT-chat **V48 Creation Request**, aangeleverd door de eigenaar. Voor publicatie is uitsluitend het standaard lokale wasmachineadres vervangen door `192.0.2.10`; de bediening en schedulerlogica zijn behouden.

De bron is op syntax en ingebouwde geheimen gecontroleerd. Er is geen verbinding met de wasmachine gemaakt en er zijn geen opdrachten aan de wasmachine verzonden.
