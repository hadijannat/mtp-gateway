import { create } from 'zustand';
import { servicesApi } from '../api';
import type {
  ServiceCommand,
  ServiceResponse,
  ServiceState,
  WSStateChangePayload,
} from '../types';

interface ServicesState {
  services: Map<string, ServiceResponse>;
  serviceList: ServiceResponse[];
  isLoading: boolean;
  error: string | null;
  commandPending: string | null; // Service name with pending command

  // Actions
  fetchServices: () => Promise<void>;
  sendCommand: (
    serviceName: string,
    command: ServiceCommand,
    procedureId?: number
  ) => Promise<boolean>;
  updateServiceState: (payload: WSStateChangePayload) => void;
  getService: (name: string) => ServiceResponse | undefined;
}

// Valid commands for each state (PackML state machine)
const VALID_COMMANDS: Record<ServiceState, ServiceCommand[]> = {
  UNDEFINED: [],
  IDLE: ['START', 'ABORT'],
  STARTING: ['ABORT'],
  EXECUTE: ['STOP', 'HOLD', 'SUSPEND', 'ABORT'],
  COMPLETING: ['ABORT'],
  COMPLETE: ['RESET', 'ABORT'],
  RESETTING: ['ABORT'],
  HOLDING: ['ABORT'],
  HELD: ['UNHOLD', 'ABORT'],
  UNHOLDING: ['ABORT'],
  SUSPENDING: ['ABORT'],
  SUSPENDED: ['UNSUSPEND', 'ABORT'],
  UNSUSPENDING: ['ABORT'],
  STOPPING: ['ABORT'],
  STOPPED: ['RESET', 'ABORT'],
  ABORTING: [],
  ABORTED: ['CLEAR'],
  CLEARING: [],
};

export const getValidCommands = (state: ServiceState): ServiceCommand[] => {
  return VALID_COMMANDS[state] ?? [];
};

export const useServicesStore = create<ServicesState>((set, get) => ({
  services: new Map(),
  serviceList: [],
  isLoading: false,
  error: null,
  commandPending: null,

  fetchServices: async () => {
    set({ isLoading: true, error: null });

    try {
      const response = await servicesApi.list();

      const services = new Map<string, ServiceResponse>();
      for (const service of response.services) {
        services.set(service.name, service);
      }

      set({
        services,
        serviceList: response.services,
        isLoading: false,
      });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch services',
        isLoading: false,
      });
    }
  },

  sendCommand: async (serviceName, command, procedureId) => {
    set({ commandPending: serviceName, error: null });

    try {
      const response = await servicesApi.command(serviceName, {
        command,
        procedure_id: procedureId,
      });

      if (response.success) {
        // Update local state
        const services = new Map(get().services);
        const existing = services.get(serviceName);

        if (existing) {
          services.set(serviceName, {
            ...existing,
            state: response.current_state,
          });

          const serviceList = get().serviceList.map((s) =>
            s.name === serviceName ? { ...s, state: response.current_state } : s
          );

          set({ services, serviceList });
        }
      }

      set({ commandPending: null });
      return response.success;
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Command failed',
        commandPending: null,
      });
      return false;
    }
  },

  updateServiceState: (payload) => {
    const { service_name, to_state, timestamp } = payload;

    const existing = get().services.get(service_name);
    if (!existing) return;

    const updatedService: ServiceResponse = {
      ...existing,
      state: to_state,
      state_time: timestamp,
    };

    const services = new Map(get().services);
    services.set(service_name, updatedService);

    const serviceList = get().serviceList.map((s) =>
      s.name === service_name ? updatedService : s
    );

    set({ services, serviceList });
  },

  getService: (name) => {
    return get().services.get(name);
  },
}));
