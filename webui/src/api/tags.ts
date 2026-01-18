import apiClient from './client';
import type { TagListResponse, TagValue, TagWriteRequest } from '../types';

export const tagsApi = {
  /**
   * Get all tags with current values
   */
  list: async (): Promise<TagListResponse> => {
    const response = await apiClient.get<TagListResponse>('/tags');
    return response.data;
  },

  /**
   * Get a single tag by name
   */
  get: async (name: string): Promise<TagValue> => {
    const response = await apiClient.get<TagValue>(`/tags/${encodeURIComponent(name)}`);
    return response.data;
  },

  /**
   * Write a value to a tag
   */
  write: async (name: string, value: TagWriteRequest): Promise<TagValue> => {
    const response = await apiClient.post<TagValue>(
      `/tags/${encodeURIComponent(name)}`,
      value
    );
    return response.data;
  },
};
