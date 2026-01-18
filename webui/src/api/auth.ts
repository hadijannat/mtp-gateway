import apiClient from './client';
import type { LoginRequest, LoginResponse, TokenResponse, User } from '../types';

export const authApi = {
  /**
   * Login with username and password
   */
  login: async (credentials: LoginRequest): Promise<LoginResponse> => {
    const response = await apiClient.post<LoginResponse>('/auth/login', credentials);
    return response.data;
  },

  /**
   * Refresh access token using refresh token
   */
  refresh: async (refreshToken: string): Promise<TokenResponse> => {
    const response = await apiClient.post<TokenResponse>('/auth/refresh', {
      refresh_token: refreshToken,
    });
    return response.data;
  },

  /**
   * Get current user info
   */
  me: async (): Promise<User> => {
    const response = await apiClient.get<User>('/auth/me');
    return response.data;
  },

  /**
   * Logout - clears local tokens
   */
  logout: (): void => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  },
};
