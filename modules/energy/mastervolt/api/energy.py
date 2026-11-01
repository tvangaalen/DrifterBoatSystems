"""The dashboard data: sources, storage and loads, with the House SOC from the DALY BMS units."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..runtime import Services
from .deps import blocking, services

router = APIRouter(tags=["energy"])


def _soc_source(details: dict) -> str:
    if details["soc"] is not None:
        return "daly_bms_average"
    return "daly_bms_stale" if details["stale_batteries"] else "daly_bms_unavailable"


def _with_house_soc(svc: Services) -> dict:
    """The MasterBus picture, with the House battery's SOC and cell figures replaced by the fresh DALY readings.

    The MasterShunt SOC is deliberately not used for the house bank: the three BMS units are the authority (and there is
    no MasterShunt fallback), so a stale or missing BMS reading shows as unavailable rather than as an old number.
    """
    data = svc.masterbus.energy()
    details = svc.house_soc_details()
    if "house" in data.get("storage", {}):
        house = data["storage"]["house"]
        house["soc"] = details["soc"]
        house["soc_source"] = _soc_source(details)
        house["soc_fresh_batteries"] = details["fresh_batteries"]
        house["soc_age_seconds"] = details["youngest_age_seconds"]
        for key in ("max_cell_mv", "max_cell_battery", "max_spread_mv", "max_spread_battery"):
            house[key] = details.get(key)
    return data


@router.get("/api/energy")
async def energy(svc: Services = Depends(services)):
    return await blocking(_with_house_soc, svc, error=503)
