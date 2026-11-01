# v0.18.0 — Mastervolt product pictures on tiles

The four supplied Mastervolt product photos replace the generic tile icons:

- Shore Power
  `5548_walstroomkabel15m25mm.jpg`
- Charger House
  `7415_combimaster123000rv.jpg`
- Alternator
  `7476_dynamo12130multigroove.jpg`
- Solar
  `6904_scm60mpptmbrv.jpg`

Local caching
-------------
The browser never hotlinks the Mastervolt site.

At server startup, `cache_product_images.py` downloads missing files into:

`static/products/`

After that, the dashboard serves only local URLs. Existing cached files are
left untouched. The PWA service worker also stores the local product images
for offline display.

Manual refresh:
`py cache_product_images.py --force`

If the server has no internet access on the first run, the dashboard falls
back to the previous emoji icon and retries caching on the next server start.
