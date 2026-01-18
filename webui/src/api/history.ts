import apiClient from './client';
import type {
  HistoryResponse,
  MultiTagHistoryResponse,
  AvailableTagsResponse,
  AggregateFunction,
} from '../types';

export interface HistoryQueryParams {
  tag: string;
  start: string; // ISO datetime
  end: string; // ISO datetime
  aggregate?: AggregateFunction;
  bucket?: string; // e.g., '1 minute', '1 hour'
  limit?: number;
}

export interface MultiTagHistoryQueryParams {
  tags: string[];
  start: string;
  end: string;
  aggregate?: AggregateFunction;
  bucket?: string;
  limit?: number;
}

export const historyApi = {
  /**
   * Get history for a single tag
   */
  getTagHistory: async (params: HistoryQueryParams): Promise<HistoryResponse> => {
    const searchParams = new URLSearchParams();
    searchParams.set('tag', params.tag);
    searchParams.set('start', params.start);
    searchParams.set('end', params.end);
    if (params.aggregate) searchParams.set('aggregate', params.aggregate);
    if (params.bucket) searchParams.set('bucket', params.bucket);
    if (params.limit) searchParams.set('limit', params.limit.toString());

    const response = await apiClient.get<HistoryResponse>(
      `/history/tags?${searchParams.toString()}`
    );
    return response.data;
  },

  /**
   * Get history for multiple tags
   */
  getMultiTagHistory: async (
    params: MultiTagHistoryQueryParams
  ): Promise<MultiTagHistoryResponse> => {
    const searchParams = new URLSearchParams();
    // Multiple tags as comma-separated
    searchParams.set('tags', params.tags.join(','));
    searchParams.set('start', params.start);
    searchParams.set('end', params.end);
    if (params.aggregate) searchParams.set('aggregate', params.aggregate);
    if (params.bucket) searchParams.set('bucket', params.bucket);
    if (params.limit) searchParams.set('limit', params.limit.toString());

    const response = await apiClient.get<MultiTagHistoryResponse>(
      `/history/tags/multi?${searchParams.toString()}`
    );
    return response.data;
  },

  /**
   * Get available tags with history data
   */
  getAvailableTags: async (): Promise<AvailableTagsResponse> => {
    const response = await apiClient.get<AvailableTagsResponse>('/history/tags/available');
    return response.data;
  },
};
