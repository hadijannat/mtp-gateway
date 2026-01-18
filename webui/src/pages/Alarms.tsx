import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  Bell,
  CheckCircle,
  RefreshCw,
  Filter,
  Check,
  Trash2,
} from 'lucide-react';
import { useAlarmsStore } from '../store';
import { useWebSocket } from '../hooks/useWebSocket';
import type { AlarmResponse, AlarmState } from '../types';

const PRIORITY_LABELS: Record<number, string> = {
  1: 'Critical',
  2: 'High',
  3: 'Medium',
  4: 'Low',
};

const PRIORITY_COLORS: Record<number, string> = {
  1: 'text-status-alarm bg-status-alarm/20 border-status-alarm/30',
  2: 'text-status-warning bg-status-warning/20 border-status-warning/30',
  3: 'text-status-uncertain bg-status-uncertain/20 border-status-uncertain/30',
  4: 'text-text-secondary bg-bg-tertiary border-border-default',
};

const STATE_COLORS: Record<AlarmState, string> = {
  active: 'text-status-alarm',
  acknowledged: 'text-status-warning',
  cleared: 'text-status-good',
  shelved: 'text-text-muted',
};

export default function Alarms() {
  const {
    alarms,
    activeCount,
    unacknowledgedCount,
    fetchAlarms,
    acknowledgeAlarm,
    clearAlarm,
    addAlarm,
    updateAlarm,
    isLoading,
  } = useAlarmsStore();

  const [filter, setFilter] = useState<AlarmState | 'all'>('all');
  const [selectedAlarms, setSelectedAlarms] = useState<Set<number>>(new Set());
  const [ackPending, setAckPending] = useState<Set<number>>(new Set());

  // WebSocket for real-time alarm updates
  useWebSocket({
    onAlarm: (payload) => {
      if (payload.action === 'raised') {
        addAlarm(payload.alarm);
      } else {
        updateAlarm(payload.alarm);
      }
    },
  });

  useEffect(() => {
    fetchAlarms();
  }, [fetchAlarms]);

  // Filter alarms
  const filteredAlarms =
    filter === 'all'
      ? alarms
      : alarms.filter((alarm) => alarm.state === filter);

  // Handle acknowledge
  const handleAcknowledge = async (alarmId: number) => {
    setAckPending((prev) => new Set(prev).add(alarmId));
    await acknowledgeAlarm(alarmId);
    setAckPending((prev) => {
      const next = new Set(prev);
      next.delete(alarmId);
      return next;
    });
    setSelectedAlarms((prev) => {
      const next = new Set(prev);
      next.delete(alarmId);
      return next;
    });
  };

  // Handle clear
  const handleClear = async (alarmId: number) => {
    setAckPending((prev) => new Set(prev).add(alarmId));
    await clearAlarm(alarmId);
    setAckPending((prev) => {
      const next = new Set(prev);
      next.delete(alarmId);
      return next;
    });
  };

  // Bulk acknowledge
  const handleBulkAcknowledge = async () => {
    const activeSelected = Array.from(selectedAlarms).filter((id) => {
      const alarm = alarms.find((a) => a.id === id);
      return alarm?.state === 'active';
    });

    for (const id of activeSelected) {
      await handleAcknowledge(id);
    }
  };

  // Toggle selection
  const toggleSelection = (alarmId: number) => {
    setSelectedAlarms((prev) => {
      const next = new Set(prev);
      if (next.has(alarmId)) {
        next.delete(alarmId);
      } else {
        next.add(alarmId);
      }
      return next;
    });
  };

  // Select all visible
  const selectAll = () => {
    setSelectedAlarms(new Set(filteredAlarms.map((a) => a.id)));
  };

  // Clear selection
  const clearSelection = () => {
    setSelectedAlarms(new Set());
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Alarms</h1>
          <p className="text-text-secondary text-sm mt-1">
            ISA-18.2 compliant alarm management
          </p>
        </div>

        <button
          onClick={() => fetchAlarms()}
          disabled={isLoading}
          className="btn-secondary flex items-center gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card p-4 flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-status-alarm/20 flex items-center justify-center">
            <AlertTriangle className="w-5 h-5 text-status-alarm" />
          </div>
          <div>
            <p className="text-text-secondary text-sm">Active</p>
            <p className="text-xl font-semibold text-text-primary">{activeCount}</p>
          </div>
        </div>

        <div className="card p-4 flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-status-warning/20 flex items-center justify-center">
            <Bell className="w-5 h-5 text-status-warning" />
          </div>
          <div>
            <p className="text-text-secondary text-sm">Unacknowledged</p>
            <p className="text-xl font-semibold text-text-primary">
              {unacknowledgedCount}
            </p>
          </div>
        </div>

        <div className="card p-4 flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-status-good/20 flex items-center justify-center">
            <CheckCircle className="w-5 h-5 text-status-good" />
          </div>
          <div>
            <p className="text-text-secondary text-sm">Total</p>
            <p className="text-xl font-semibold text-text-primary">{alarms.length}</p>
          </div>
        </div>
      </div>

      {/* Filters and bulk actions */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-text-muted" />
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as AlarmState | 'all')}
            className="input text-sm"
          >
            <option value="all">All States</option>
            <option value="active">Active</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="cleared">Cleared</option>
            <option value="shelved">Shelved</option>
          </select>
        </div>

        {/* Bulk actions */}
        {selectedAlarms.size > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-text-muted">
              {selectedAlarms.size} selected
            </span>
            <button onClick={clearSelection} className="btn-secondary text-sm">
              Clear
            </button>
            <button
              onClick={handleBulkAcknowledge}
              className="btn-primary text-sm flex items-center gap-1"
            >
              <Check className="w-4 h-4" />
              Acknowledge Selected
            </button>
          </div>
        )}

        {selectedAlarms.size === 0 && filteredAlarms.length > 0 && (
          <button onClick={selectAll} className="text-sm text-accent-primary hover:underline">
            Select all
          </button>
        )}
      </div>

      {/* Alarm table */}
      <div className="card overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-bg-tertiary text-text-secondary text-sm">
              <th className="px-4 py-3 text-left w-10">
                <input
                  type="checkbox"
                  checked={
                    selectedAlarms.size > 0 &&
                    selectedAlarms.size === filteredAlarms.length
                  }
                  onChange={(e) =>
                    e.target.checked ? selectAll() : clearSelection()
                  }
                  className="rounded border-border-default"
                />
              </th>
              <th className="px-4 py-3 text-left">Alarm</th>
              <th className="px-4 py-3 text-left">Source</th>
              <th className="px-4 py-3 text-left">Priority</th>
              <th className="px-4 py-3 text-left">State</th>
              <th className="px-4 py-3 text-left">Time</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredAlarms.map((alarm) => (
              <AlarmRow
                key={alarm.id}
                alarm={alarm}
                isSelected={selectedAlarms.has(alarm.id)}
                isPending={ackPending.has(alarm.id)}
                onToggleSelect={() => toggleSelection(alarm.id)}
                onAcknowledge={() => handleAcknowledge(alarm.id)}
                onClear={() => handleClear(alarm.id)}
              />
            ))}
          </tbody>
        </table>

        {/* Empty state */}
        {filteredAlarms.length === 0 && !isLoading && (
          <div className="p-8 text-center text-text-muted">
            {filter === 'all'
              ? 'No alarms to display'
              : `No ${filter} alarms`}
          </div>
        )}
      </div>
    </div>
  );
}

// Alarm row component
interface AlarmRowProps {
  alarm: AlarmResponse;
  isSelected: boolean;
  isPending: boolean;
  onToggleSelect: () => void;
  onAcknowledge: () => void;
  onClear: () => void;
}

function AlarmRow({
  alarm,
  isSelected,
  isPending,
  onToggleSelect,
  onAcknowledge,
  onClear,
}: AlarmRowProps) {
  const isActive = alarm.state === 'active';
  const isAcknowledged = alarm.state === 'acknowledged';

  return (
    <tr
      className={`table-row ${isActive && alarm.priority <= 2 ? 'alarm-active' : ''}`}
    >
      <td className="px-4 py-3">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onToggleSelect}
          className="rounded border-border-default"
        />
      </td>
      <td className="px-4 py-3">
        <p className="font-medium text-text-primary">{alarm.alarm_id}</p>
        <p className="text-sm text-text-muted truncate max-w-xs">{alarm.message}</p>
      </td>
      <td className="px-4 py-3 text-text-secondary">{alarm.source}</td>
      <td className="px-4 py-3">
        <span
          className={`px-2 py-1 rounded text-xs font-medium border ${
            PRIORITY_COLORS[alarm.priority]
          }`}
        >
          {PRIORITY_LABELS[alarm.priority]}
        </span>
      </td>
      <td className="px-4 py-3">
        <span className={`font-medium ${STATE_COLORS[alarm.state]}`}>
          {alarm.state.charAt(0).toUpperCase() + alarm.state.slice(1)}
        </span>
        {alarm.acknowledged_by && (
          <p className="text-xs text-text-muted">by {alarm.acknowledged_by}</p>
        )}
      </td>
      <td className="px-4 py-3 text-sm text-text-muted">
        {new Date(alarm.raised_at).toLocaleString()}
      </td>
      <td className="px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-2">
          {isActive && (
            <button
              onClick={onAcknowledge}
              disabled={isPending}
              className="btn-primary text-xs py-1 px-2 flex items-center gap-1"
            >
              {isPending ? (
                <RefreshCw className="w-3 h-3 animate-spin" />
              ) : (
                <Check className="w-3 h-3" />
              )}
              Ack
            </button>
          )}
          {isAcknowledged && (
            <button
              onClick={onClear}
              disabled={isPending}
              className="btn-secondary text-xs py-1 px-2 flex items-center gap-1"
            >
              {isPending ? (
                <RefreshCw className="w-3 h-3 animate-spin" />
              ) : (
                <Trash2 className="w-3 h-3" />
              )}
              Clear
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
