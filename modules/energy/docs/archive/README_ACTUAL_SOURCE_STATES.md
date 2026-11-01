# v0.17.5 — actual Solar and Alternator charge states

The Solar and Alternator source tiles now display the actual MasterBus
charger-state fields instead of derived states.

Solar / SCM Solar [31B483]
- field 3 = Charge state

Alternator / APR Alpha Pro MB [329B8C]
- field 5 = Charger state

Decoder:
- 0 = Off
- 1 = Bulk
- 2 = Absorption
- 3 = Float

Unexpected values are shown as `Unknown (n)`; the dashboard no longer infers
Solar state from current or Alternator state from shaft speed/current.

No existing voltage/current/power mappings or control mappings were changed.
