"""The HTTP API. One module per area; `routers` lists them for the application factory."""

from . import balancers, bluetooth, bms, controls, energy, history, reports, settings, system

routers = (
    system.router,
    energy.router,
    settings.router,
    controls.router,
    bms.router,
    balancers.router,
    bluetooth.router,
    history.router,
    reports.router,
)
