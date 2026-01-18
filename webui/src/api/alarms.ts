import apiClient from './client';
import type {
  AlarmAckRequest,
  AlarmAckResponse,
  AlarmListResponse,
  AlarmResponse,
  AlarmState,
} from '../types';

export const alarmsApi = {
  /**
   * Get all alarms with optional filtering
   */
  list: async (params?: {
    state?: AlarmState;
    priority?: number;
    limit?: number;
    offset?: number;
  }): Promise<AlarmListResponse> => {
    const response = await apiClient.get<AlarmListResponse>('/alarms', { params });
    return response.data;
  },

  /**
   * Get a single alarm by ID
   */
  get: async (id: number): Promise<AlarmResponse> => {
    const response = await apiClient.get<AlarmResponse>(`/alarms/${id}`);
    return response.data;
  },

  /**
   * Acknowledge an alarm
   */
  acknowledge: async (id: number, request?: AlarmAckRequest): Promise<AlarmAckResponse> => {
    const response = await apiClient.post<AlarmAckResponse>(
      `/alarms/${id}/acknowledge`,
      request ?? {}
    );
    return response.data;
  },

  /**
   * Clear an acknowledged alarm
   */
  clear: async (id: number): Promise<AlarmResponse> => {
    const response = await apiClient.post<AlarmResponse>(`/alarms/${id}/clear`);
    return response.data;
  },
};
