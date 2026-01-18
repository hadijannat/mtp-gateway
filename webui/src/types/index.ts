// API Types - matches backend Pydantic schemas

// Auth types
export interface User {
  id: number;
  username: string;
  email: string;
  role: Role;
  is_active: boolean;
  permissions: string[];
}

export type Role = 'operator' | 'engineer' | 'admin';

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

// Tag types
export type TagQuality = 'good' | 'uncertain' | 'bad' | 'offline';

export interface TagValue {
  name: string;
  value: number | string | boolean | null;
  quality: TagQuality;
  timestamp: string;
  unit?: string;
  description?: string;
}

export interface TagWriteRequest {
  value: number | string | boolean;
}

export interface TagListResponse {
  tags: TagValue[];
  count: number;
}

// Service types
export type ServiceState =
  | 'UNDEFINED'
  | 'IDLE'
  | 'STARTING'
  | 'EXECUTE'
  | 'COMPLETING'
  | 'COMPLETE'
  | 'RESETTING'
  | 'HOLDING'
  | 'HELD'
  | 'UNHOLDING'
  | 'SUSPENDING'
  | 'SUSPENDED'
  | 'UNSUSPENDING'
  | 'STOPPING'
  | 'STOPPED'
  | 'ABORTING'
  | 'ABORTED'
  | 'CLEARING';

export type ServiceCommand =
  | 'START'
  | 'STOP'
  | 'HOLD'
  | 'UNHOLD'
  | 'SUSPEND'
  | 'UNSUSPEND'
  | 'ABORT'
  | 'CLEAR'
  | 'RESET';

export interface ProcedureInfo {
  id: number;
  name: string;
  is_default: boolean;
}

export interface ServiceResponse {
  name: string;
  state: ServiceState;
  state_time?: string;
  procedure_id?: number;
  procedure_name?: string;
  procedures: ProcedureInfo[];
  interlocked: boolean;
  interlock_reason?: string;
  mode: string;
}

export interface ServiceCommandRequest {
  command: ServiceCommand;
  procedure_id?: number;
}

export interface ServiceCommandResponse {
  success: boolean;
  service_name: string;
  command: ServiceCommand;
  previous_state: ServiceState;
  current_state: ServiceState;
  message?: string;
}

export interface ServiceListResponse {
  services: ServiceResponse[];
  count: number;
}

// Alarm types - ISA-18.2 compliant
export type AlarmState = 'active' | 'acknowledged' | 'cleared' | 'shelved';

export interface AlarmResponse {
  id: number;
  alarm_id: string;
  source: string;
  priority: number;
  state: AlarmState;
  message: string;
  value?: number;
  raised_at: string;
  acknowledged_at?: string;
  acknowledged_by?: string;
  cleared_at?: string;
  shelved_until?: string;
}

export interface AlarmListResponse {
  alarms: AlarmResponse[];
  count: number;
  active_count: number;
  unacknowledged_count: number;
}

export interface AlarmAckRequest {
  comment?: string;
}

export interface AlarmAckResponse {
  success: boolean;
  alarm_id: number;
  acknowledged_at: string;
  acknowledged_by: string;
}

// Health types
export interface HealthResponse {
  status: string;
  version: string;
  uptime_seconds: number;
  timestamp: string;
}

// WebSocket message types
export type WSMessageType =
  | 'subscribe'
  | 'unsubscribe'
  | 'ping'
  | 'pong'
  | 'tag_update'
  | 'state_change'
  | 'alarm';

export type WSChannel = 'tags' | 'services' | 'alarms' | 'all';

export interface WSMessage<T = unknown> {
  type: WSMessageType;
  payload: T;
}

export interface WSSubscribePayload {
  channel: WSChannel;
  tags?: string[];
}

export interface WSTagUpdatePayload {
  tag_name: string;
  value: number | string | boolean | null;
  quality: TagQuality;
  timestamp: string;
}

export interface WSStateChangePayload {
  service_name: string;
  from_state: ServiceState;
  to_state: ServiceState;
  timestamp: string;
}

export interface WSAlarmPayload {
  action: 'raised' | 'acknowledged' | 'cleared';
  alarm: AlarmResponse;
}

// History types
export type AggregateFunction = 'avg' | 'min' | 'max' | 'first' | 'last';

export interface HistoryPoint {
  time: string;
  value: number | null;
  quality: TagQuality;
}

export interface HistoryResponse {
  tag_name: string;
  points: HistoryPoint[];
  count: number;
  start_time: string;
  end_time: string;
  aggregate?: AggregateFunction;
  bucket?: string;
}

export interface MultiTagHistoryResponse {
  tags: Record<string, HistoryPoint[]>;
  count: number;
  start_time: string;
  end_time: string;
  aggregate?: AggregateFunction;
  bucket?: string;
}

export interface AvailableTagsResponse {
  tags: string[];
  count: number;
}

// API error
export interface ApiError {
  detail: string;
  status_code?: number;
}
