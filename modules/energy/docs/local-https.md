# Mastervolt local HTTPS

The application uses a private certificate authority stored only on the Mastervolt PC. It does not require a public domain, cloud service, port forwarding, or internet publication.

## PC

Run `start_mastervolt_server.cmd`. It automatically:

1. creates or reuses the private **Mastervolt Local CA**;
2. issues a fresh server certificate for localhost, the computer name, and all current local IPv4 addresses;
3. trusts the CA for the current Windows user;
4. selects a private RFC1918 LAN address and starts Uvicorn on HTTPS port 8000 bound only to that address.

The first time, double-click `install_pc_certificate.cmd` from Windows Explorer. It trusts the public CA for the interactive Windows/browser account and opens the correct HTTPS address automatically. This separate one-click step is needed when the server was deployed by a service or sandbox account. No copying or command-line input is required.

Afterward, open the `https://...:8000` address displayed by the start script. When no private LAN address is available, it falls back to `127.0.0.1` for PC-only access.

## iPhone — required once

1. Run `install_iphone_certificate.cmd` on the PC.
2. Open the displayed `http://...:8001/Mastervolt-Local-CA.cer` address in Safari on the iPhone.
3. Allow the configuration profile download, then stop the temporary installer with Ctrl+C.
4. On the iPhone, open **Settings → General → VPN & Device Management** and install **Mastervolt Local CA**.
5. Open **Settings → General → About → Certificate Trust Settings** and enable full trust for **Mastervolt Local CA**.
6. Open the app using the matching local address, for example `https://192.168.1.20:8000`.

The temporary port 8001 helper is also bound only to the selected private address. It serves only the public CA certificate and runs only until Ctrl+C is pressed. The CA private key is never served and remains in `certs\ca-key.pem` on the PC.

If the PC receives a different local IP address, restart the HTTPS server so it issues a server certificate containing the new address. The CA does not change, so the iPhone profile does not need to be installed again.
