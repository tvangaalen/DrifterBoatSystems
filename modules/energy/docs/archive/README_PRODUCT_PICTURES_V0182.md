# v0.18.2 — product pictures for remaining tiles

Added local product-image mappings for:

- House battery -> `battery.jpg`
- Start battery -> `battery.jpg`
- Bowthruster battery -> `battery.jpg`
- Charger Start -> `charger_macplus.jpeg`
- Charger Bowthruster -> `charger_macplus.jpeg`
- Engine ECU -> `yanmar_ecu.jpg`
- AC Loads -> `ac_loads.jpg`
- Other DC loads -> `other_dc.png`

The cache manifest now contains all supplied source URLs. The browser only uses
local `/static/products/...` paths. Shared source images are cached once and used
by multiple tiles.

Run manually to populate/refresh the local cache:

`py cache_product_images.py --force`

If a source CDN rejects automated downloading, the tile keeps the previous icon
fallback until the corresponding local file becomes available.
