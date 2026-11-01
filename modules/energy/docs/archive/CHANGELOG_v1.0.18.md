# Mastervolt Web App v1.0.18

## Changes

- Replaced the normal HTTP startup with local HTTPS on port 8000.
- Added automatic creation of a private Mastervolt local CA and a renewable server certificate containing localhost, the computer name, and current local IPv4 addresses.
- Added automatic trust installation for the current Windows user.
- Added `install_pc_certificate.cmd` for one-click trust installation in the interactive browser account when deployment was performed by a service or sandbox account.
- Added a one-time iPhone CA-certificate installer that temporarily serves only the public certificate on local port 8001.
- Added a protected HTTPS endpoint at `/local-ca.cer` for retrieving the public CA certificate after HTTPS trust is established.
- The server binds only to a selected RFC1918 private-LAN address (or localhost fallback), not to all interfaces or a public address.
- No public domain, cloud certificate provider, port forwarding, or internet publication is used.
- Updated the application version, footer, and service-worker cache to v1.0.18.
