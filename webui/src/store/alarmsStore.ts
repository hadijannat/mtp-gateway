import { create } from 'zustand';
import { alarmsApi } from '../api';
import type { AlarmResponse, AlarmState } from '../types';

interface AlarmsState {
  alarms: AlarmResponse[];
  activeCount: number;
  unacknowledgedCount: number;
  highestPriority: number;
  isLoading: boolean;
  error: string | null;

  // Actions
  fetchAlarms: (filter?: { state?: AlarmState; priority?: number }) => Promise<void>;
  acknowledgeAlarm: (id: number, comment?: string) => Promise<boolean>;
  clearAlarm: (id: number) => Promise<boolean>;
  updateAlarm: (alarm: AlarmResponse) => void;
  addAlarm: (alarm: AlarmResponse) => void;
}

export const useAlarmsStore = create<AlarmsState>((set, get) => ({
  alarms: [],
  activeCount: 0,
  unacknowledgedCount: 0,
  highestPriority: 4, // 4 = lowest priority
  isLoading: false,
  error: null,

  fetchAlarms: async (filter) => {
    set({ isLoading: true, error: null });

    try {
      const response = await alarmsApi.list(filter);

      // Calculate highest priority (lowest number = highest priority)
      let highestPriority = 4;
      for (const alarm of response.alarms) {
        if (alarm.state === 'active' && alarm.priority < highestPriority) {
          highestPriority = alarm.priority;
        }
      }

      set({
        alarms: response.alarms,
        activeCount: response.active_count,
        unacknowledgedCount: response.unacknowledged_count,
        highestPriority,
        isLoading: false,
      });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch alarms',
        isLoading: false,
      });
    }
  },

  acknowledgeAlarm: async (id, comment) => {
    try {
      await alarmsApi.acknowledge(id, comment ? { comment } : undefined);

      // Update local state
      const alarms = get().alarms.map((alarm) =>
        alarm.id === id
          ? { ...alarm, state: 'acknowledged' as AlarmState }
          : alarm
      );

      const unacknowledgedCount = alarms.filter(
        (a) => a.state === 'active'
      ).length;

      set({ alarms, unacknowledgedCount });
      return true;
    } catch {
      return false;
    }
  },

  clearAlarm: async (id) => {
    try {
      await alarmsApi.clear(id);

      // Update local state
      const alarms = get().alarms.map((alarm) =>
        alarm.id === id ? { ...alarm, state: 'cleared' as AlarmState } : alarm
      );

      const activeCount = alarms.filter(
        (a) => a.state === 'active' || a.state === 'acknowledged'
      ).length;

      set({ alarms, activeCount });
      return true;
    } catch {
      return false;
    }
  },

  updateAlarm: (updatedAlarm) => {
    const alarms = get().alarms.map((alarm) =>
      alarm.id === updatedAlarm.id ? updatedAlarm : alarm
    );

    const activeCount = alarms.filter(
      (a) => a.state === 'active' || a.state === 'acknowledged'
    ).length;
    const unacknowledgedCount = alarms.filter((a) => a.state === 'active').length;

    let highestPriority = 4;
    for (const alarm of alarms) {
      if (alarm.state === 'active' && alarm.priority < highestPriority) {
        highestPriority = alarm.priority;
      }
    }

    set({ alarms, activeCount, unacknowledgedCount, highestPriority });
  },

  addAlarm: (newAlarm) => {
    const alarms = [newAlarm, ...get().alarms];

    const activeCount = alarms.filter(
      (a) => a.state === 'active' || a.state === 'acknowledged'
    ).length;
    const unacknowledgedCount = alarms.filter((a) => a.state === 'active').length;

    let highestPriority = 4;
    for (const alarm of alarms) {
      if (alarm.state === 'active' && alarm.priority < highestPriority) {
        highestPriority = alarm.priority;
      }
    }

    set({ alarms, activeCount, unacknowledgedCount, highestPriority });
  },
}));
