import apiClient from './client';
import type { HealthResponse } from '../types';

export const healthApi = {
  /**
   * Get system health status
   */
  check: async (): Promise<HealthResponse> => {
    const response = await apiClient.get<HealthResponse>('/health');
    return response.data;
  },

  /**
   * Check if system is ready
   */
  ready: async (): Promise<{ ready: boolean }> => {
    const response = await apiClient.get<{ ready: boolean }>('/health/ready');
    return response.data;
  },
};
