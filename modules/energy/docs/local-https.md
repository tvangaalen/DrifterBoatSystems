# Mastervolt local HTTPS

The application uses a private certificate authority stored only on the Mastervolt PC. It does not require a public domain, cloud service, port forwarding, or internet publication.

## PC

`setup_local_https.ps1` creates the private **Mastervolt Local CA** once (or reuses it) in `certs\`. The Drifter app's
certificate is issued from it (`setup_https.ps1` of Drifter Boat Systems, through `common\issue_cert.ps1`); MasterVolt itself
serves plain HTTP on 127.0.0.1 since 2.2.0. Never delete or recreate the CA: every device would have to be set up again.

To let a browser on this PC trust it, double-click `install_pc_certificate.cmd` once (it trusts the CA for the current
Windows user).

## iPhone — required once

1. Run `install_iphone_certificate.cmd` on the PC.
2. Open the displayed `http://...:8001/Mastervolt-Local-CA.cer` address in Safari on the iPhone.
3. Allow the configuration profile download, then stop the temporary installer with Ctrl+C.
4. On the iPhone, open **Settings → General → VPN & Device Management** and install **Mastervolt Local CA**.
5. Open **Settings → General → About → Certificate Trust Settings** and enable full trust for **Mastervolt Local CA**.
6. Open the Drifter app, for example `https://192.168.1.166:8100/`.

The temporary port 8001 helper is also bound only to the selected private address. It serves only the public CA certificate and runs only until Ctrl+C is pressed. The CA private key is never served and remains in `certs\ca-key.pem` on the PC.
