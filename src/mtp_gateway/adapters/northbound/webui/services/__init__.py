"""WebUI background services.

Provides background services for alarm detection and history recording:
- AlarmDetector: Monitors AnaMon/BinMon values and raises/clears alarms
- HistoryRecorder: Records tag value changes to TimescaleDB
"""

from mtp_gateway.adapters.northbound.webui.services.alarm_detector import AlarmDetector
from mtp_gateway.adapters.northbound.webui.services.history_recorder import HistoryRecorder

__all__ = [
    "AlarmDetector",
    "HistoryRecorder",
]
