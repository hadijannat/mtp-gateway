import { useEffect, useRef, useCallback, useState } from 'react';
import type {
  WSChannel,
  WSMessage,
  WSSubscribePayload,
  WSTagUpdatePayload,
  WSStateChangePayload,
  WSAlarmPayload,
} from '../types';

type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'error';

interface UseWebSocketOptions {
  onTagUpdate?: (payload: WSTagUpdatePayload) => void;
  onStateChange?: (payload: WSStateChangePayload) => void;
  onAlarm?: (payload: WSAlarmPayload) => void;
  autoReconnect?: boolean;
  reconnectInterval?: number;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const {
    onTagUpdate,
    onStateChange,
    onAlarm,
    autoReconnect = true,
    reconnectInterval = 3000,
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const subscribedChannels = useRef<Set<WSChannel>>(new Set());

  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');

  // Get WebSocket URL
  const getWsUrl = useCallback(() => {
    const token = localStorage.getItem('access_token');
    if (!token) return null;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    return `${protocol}//${host}/api/v1/ws?token=${encodeURIComponent(token)}`;
  }, []);

  // Send message to WebSocket
  const send = useCallback((message: WSMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  // Subscribe to a channel
  const subscribe = useCallback(
    (channel: WSChannel, tags?: string[]) => {
      subscribedChannels.current.add(channel);

      const payload: WSSubscribePayload = { channel };
      if (tags) {
        payload.tags = tags;
      }

      send({ type: 'subscribe', payload });
    },
    [send]
  );

  // Unsubscribe from a channel
  const unsubscribe = useCallback(
    (channel: WSChannel) => {
      subscribedChannels.current.delete(channel);
      send({ type: 'unsubscribe', payload: { channel } });
    },
    [send]
  );

  // Handle incoming messages
  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const message = JSON.parse(event.data) as WSMessage;

        switch (message.type) {
          case 'tag_update':
            onTagUpdate?.(message.payload as WSTagUpdatePayload);
            break;
          case 'state_change':
            onStateChange?.(message.payload as WSStateChangePayload);
            break;
          case 'alarm':
            onAlarm?.(message.payload as WSAlarmPayload);
            break;
          case 'pong':
            // Heartbeat response, no action needed
            break;
          default:
            console.debug('Unknown WebSocket message type:', message.type);
        }
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    },
    [onTagUpdate, onStateChange, onAlarm]
  );

  // Connect to WebSocket
  const connect = useCallback(() => {
    const url = getWsUrl();
    if (!url) {
      setConnectionState('error');
      return;
    }

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    setConnectionState('connecting');

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnectionState('connected');

      // Re-subscribe to previously subscribed channels
      subscribedChannels.current.forEach((channel) => {
        send({ type: 'subscribe', payload: { channel } });
      });
    };

    ws.onmessage = handleMessage;

    ws.onerror = () => {
      setConnectionState('error');
    };

    ws.onclose = (event) => {
      setConnectionState('disconnected');

      // Auto-reconnect if enabled and not intentionally closed
      if (autoReconnect && event.code !== 1000) {
        reconnectTimeoutRef.current = window.setTimeout(() => {
          connect();
        }, reconnectInterval);
      }
    };
  }, [getWsUrl, handleMessage, send, autoReconnect, reconnectInterval]);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'User disconnect');
      wsRef.current = null;
    }

    setConnectionState('disconnected');
  }, []);

  // Ping to keep connection alive
  const ping = useCallback(() => {
    send({ type: 'ping', payload: {} });
  }, [send]);

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  // Heartbeat interval
  useEffect(() => {
    if (connectionState !== 'connected') return;

    const interval = setInterval(() => {
      ping();
    }, 30000); // 30 seconds

    return () => clearInterval(interval);
  }, [connectionState, ping]);

  return {
    connectionState,
    isConnected: connectionState === 'connected',
    connect,
    disconnect,
    subscribe,
    unsubscribe,
    send,
    ping,
  };
}
