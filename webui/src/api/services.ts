import apiClient from './client';
import type {
  ServiceCommandRequest,
  ServiceCommandResponse,
  ServiceListResponse,
  ServiceResponse,
} from '../types';

export const servicesApi = {
  /**
   * Get all services with current state
   */
  list: async (): Promise<ServiceListResponse> => {
    const response = await apiClient.get<ServiceListResponse>('/services');
    return response.data;
  },

  /**
   * Get a single service by name
   */
  get: async (name: string): Promise<ServiceResponse> => {
    const response = await apiClient.get<ServiceResponse>(
      `/services/${encodeURIComponent(name)}`
    );
    return response.data;
  },

  /**
   * Send a command to a service
   */
  command: async (
    name: string,
    request: ServiceCommandRequest
  ): Promise<ServiceCommandResponse> => {
    const response = await apiClient.post<ServiceCommandResponse>(
      `/services/${encodeURIComponent(name)}/command`,
      request
    );
    return response.data;
  },
};
