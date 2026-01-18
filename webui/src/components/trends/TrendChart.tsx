import { useEffect, useState, useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { RefreshCw, AlertCircle } from 'lucide-react';
import { historyApi } from '../../api';
import type { HistoryPoint, AggregateFunction } from '../../types';

// Chart colors for multiple tags
const CHART_COLORS = [
  '#3b82f6', // blue
  '#22c55e', // green
  '#f97316', // orange
  '#8b5cf6', // purple
  '#ef4444', // red
  '#eab308', // yellow
  '#06b6d4', // cyan
  '#ec4899', // pink
];

export interface TrendChartProps {
  /** Tag names to display */
  tags: string[];
  /** Start time (ISO string or Date) */
  startTime: Date | string;
  /** End time (ISO string or Date) */
  endTime: Date | string;
  /** Time bucket for aggregation (e.g., '1 minute', '1 hour') */
  bucket?: string;
  /** Aggregation function */
  aggregate?: AggregateFunction;
  /** Maximum data points */
  limit?: number;
  /** Auto-refresh interval in ms (0 to disable) */
  refreshInterval?: number;
  /** Chart height in pixels */
  height?: number;
  /** Show reference lines for alarm limits */
  alarmLimits?: {
    high?: number;
    highHigh?: number;
    low?: number;
    lowLow?: number;
  };
}

interface ChartDataPoint {
  time: number;
  timeLabel: string;
  [tagName: string]: number | string | null;
}

export default function TrendChart({
  tags,
  startTime,
  endTime,
  bucket = '1 minute',
  aggregate = 'avg',
  limit = 500,
  refreshInterval = 0,
  height = 300,
  alarmLimits,
}: TrendChartProps) {
  const [chartData, setChartData] = useState<ChartDataPoint[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);

  // Convert dates to ISO strings
  const startStr = useMemo(
    () => (typeof startTime === 'string' ? startTime : startTime.toISOString()),
    [startTime]
  );
  const endStr = useMemo(
    () => (typeof endTime === 'string' ? endTime : endTime.toISOString()),
    [endTime]
  );

  // Fetch history data
  const fetchData = async () => {
    if (tags.length === 0) {
      setChartData([]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await historyApi.getMultiTagHistory({
        tags,
        start: startStr,
        end: endStr,
        bucket,
        aggregate,
        limit,
      });

      // Transform data for Recharts
      // Collect all unique timestamps
      const timeMap = new Map<number, ChartDataPoint>();

      for (const [tagName, points] of Object.entries(response.tags)) {
        for (const point of points as HistoryPoint[]) {
          const timestamp = new Date(point.time).getTime();
          if (!timeMap.has(timestamp)) {
            timeMap.set(timestamp, {
              time: timestamp,
              timeLabel: formatTimeLabel(new Date(point.time)),
            });
          }
          const dataPoint = timeMap.get(timestamp)!;
          dataPoint[tagName] = point.value;
        }
      }

      // Sort by time and convert to array
      const sortedData = Array.from(timeMap.values()).sort((a, b) => a.time - b.time);

      setChartData(sortedData);
      setLastFetch(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch history data');
    } finally {
      setIsLoading(false);
    }
  };

  // Initial fetch and refresh
  useEffect(() => {
    fetchData();

    if (refreshInterval > 0) {
      const interval = setInterval(fetchData, refreshInterval);
      return () => clearInterval(interval);
    }
  }, [tags.join(','), startStr, endStr, bucket, aggregate, limit, refreshInterval]);

  // Format time label based on range
  const formatTimeLabel = (date: Date): string => {
    const range = new Date(endStr).getTime() - new Date(startStr).getTime();
    const hours = range / (1000 * 60 * 60);

    if (hours <= 1) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } else if (hours <= 24) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else {
      return date.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }
  };

  // Custom tooltip
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;

    return (
      <div className="bg-bg-elevated border border-border-default rounded-lg p-3 shadow-lg">
        <p className="text-text-secondary text-xs mb-2">{label}</p>
        {payload.map((entry: any, index: number) => (
          <div key={index} className="flex items-center gap-2">
            <div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-text-primary text-sm">
              {entry.name}: {entry.value?.toFixed(2) ?? 'N/A'}
            </span>
          </div>
        ))}
      </div>
    );
  };

  // Calculate Y-axis domain
  const yDomain = useMemo(() => {
    if (chartData.length === 0) return [0, 100];

    let min = Infinity;
    let max = -Infinity;

    for (const point of chartData) {
      for (const tag of tags) {
        const value = point[tag];
        if (typeof value === 'number' && !isNaN(value)) {
          min = Math.min(min, value);
          max = Math.max(max, value);
        }
      }
    }

    // Include alarm limits in range
    if (alarmLimits) {
      if (alarmLimits.lowLow !== undefined) min = Math.min(min, alarmLimits.lowLow);
      if (alarmLimits.low !== undefined) min = Math.min(min, alarmLimits.low);
      if (alarmLimits.high !== undefined) max = Math.max(max, alarmLimits.high);
      if (alarmLimits.highHigh !== undefined) max = Math.max(max, alarmLimits.highHigh);
    }

    // Add some padding
    const padding = (max - min) * 0.1 || 10;
    return [min - padding, max + padding];
  }, [chartData, tags, alarmLimits]);

  if (error) {
    return (
      <div className="flex items-center justify-center gap-2 p-8 text-status-alarm" style={{ height }}>
        <AlertCircle className="w-5 h-5" />
        <span>{error}</span>
      </div>
    );
  }

  return (
    <div className="relative">
      {/* Loading overlay */}
      {isLoading && (
        <div className="absolute inset-0 bg-bg-primary/50 flex items-center justify-center z-10">
          <RefreshCw className="w-6 h-6 text-accent-primary animate-spin" />
        </div>
      )}

      {/* Chart */}
      {chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={chartData} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="timeLabel"
              stroke="#6b7280"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickLine={{ stroke: '#374151' }}
            />
            <YAxis
              domain={yDomain}
              stroke="#6b7280"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickLine={{ stroke: '#374151' }}
              tickFormatter={(value) => value.toFixed(1)}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ paddingTop: '10px' }}
              formatter={(value) => <span className="text-text-primary text-sm">{value}</span>}
            />

            {/* Alarm reference lines */}
            {alarmLimits?.highHigh !== undefined && (
              <ReferenceLine
                y={alarmLimits.highHigh}
                stroke="#ef4444"
                strokeDasharray="5 5"
                label={{ value: 'HH', fill: '#ef4444', fontSize: 10 }}
              />
            )}
            {alarmLimits?.high !== undefined && (
              <ReferenceLine
                y={alarmLimits.high}
                stroke="#f97316"
                strokeDasharray="5 5"
                label={{ value: 'H', fill: '#f97316', fontSize: 10 }}
              />
            )}
            {alarmLimits?.low !== undefined && (
              <ReferenceLine
                y={alarmLimits.low}
                stroke="#f97316"
                strokeDasharray="5 5"
                label={{ value: 'L', fill: '#f97316', fontSize: 10 }}
              />
            )}
            {alarmLimits?.lowLow !== undefined && (
              <ReferenceLine
                y={alarmLimits.lowLow}
                stroke="#ef4444"
                strokeDasharray="5 5"
                label={{ value: 'LL', fill: '#ef4444', fontSize: 10 }}
              />
            )}

            {/* Tag lines */}
            {tags.map((tag, index) => (
              <Line
                key={tag}
                type="monotone"
                dataKey={tag}
                stroke={CHART_COLORS[index % CHART_COLORS.length]}
                strokeWidth={2}
                dot={false}
                connectNulls
                animationDuration={300}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div
          className="flex items-center justify-center text-text-muted"
          style={{ height }}
        >
          {isLoading ? 'Loading...' : 'No data available for selected time range'}
        </div>
      )}

      {/* Last fetch time */}
      {lastFetch && (
        <div className="text-right text-xs text-text-muted mt-2">
          Last updated: {lastFetch.toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}
