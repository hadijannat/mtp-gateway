import { Link } from 'react-router-dom';
import { AlertTriangle, Bell, ChevronRight } from 'lucide-react';
import { useAlarmsStore } from '../../store/alarmsStore';

export default function AlarmBanner() {
  const { activeCount, unacknowledgedCount, highestPriority } = useAlarmsStore();

  // Don't show if no active alarms
  if (activeCount === 0) {
    return null;
  }

  // Determine banner style based on priority
  const getBannerStyle = () => {
    if (highestPriority <= 1) {
      return 'bg-status-alarm/20 border-status-alarm text-status-alarm';
    }
    if (highestPriority === 2) {
      return 'bg-status-warning/20 border-status-warning text-status-warning';
    }
    return 'bg-status-uncertain/20 border-status-uncertain text-status-uncertain';
  };

  const getPriorityLabel = () => {
    if (highestPriority <= 1) return 'CRITICAL';
    if (highestPriority === 2) return 'HIGH';
    if (highestPriority === 3) return 'MEDIUM';
    return 'LOW';
  };

  return (
    <div className={`border-b ${getBannerStyle()} ${highestPriority <= 1 ? 'alarm-active' : ''}`}>
      <Link
        to="/alarms"
        className="flex items-center justify-between px-4 py-2 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          {highestPriority <= 2 ? (
            <AlertTriangle className="w-5 h-5" />
          ) : (
            <Bell className="w-5 h-5" />
          )}
          <span className="font-medium">
            {activeCount} Active Alarm{activeCount !== 1 ? 's' : ''}
          </span>
          {unacknowledgedCount > 0 && (
            <span className="text-sm opacity-75">
              ({unacknowledgedCount} unacknowledged)
            </span>
          )}
          <span className="px-2 py-0.5 text-xs font-semibold rounded border border-current">
            {getPriorityLabel()}
          </span>
        </div>
        <ChevronRight className="w-5 h-5" />
      </Link>
    </div>
  );
}
