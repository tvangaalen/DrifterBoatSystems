# Mastervolt Web App v1.4.12

- Added coordinated scheduling for BMS connections, BMS reads, and balancer traffic.
- Pauses BMS polling during an actual connection attempt, then uses the retry pause to refresh already connected batteries.
- Serializes BMS reads so three batteries no longer transmit simultaneously.
- Replaces the fixed 10-second balancer delay with a readiness check: all three batteries must be connected and successfully read once.
- Keeps balancer connect and read traffic behind BMS connection and read priority.
- Updated application and service-worker cache versions to v1.4.12.
