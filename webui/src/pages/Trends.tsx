import { useEffect, useState, useMemo } from 'react';
import {
  TrendingUp,
  RefreshCw,
  Calendar,
  Clock,
  Plus,
  X,
  ChevronDown,
} from 'lucide-react';
import TrendChart from '../components/trends/TrendChart';
import { historyApi } from '../api';
import type { AggregateFunction } from '../types';

// Preset time ranges
const TIME_RANGES = [
  { label: '1 Hour', value: 1, unit: 'hour' as const },
  { label: '4 Hours', value: 4, unit: 'hour' as const },
  { label: '8 Hours', value: 8, unit: 'hour' as const },
  { label: '24 Hours', value: 24, unit: 'hour' as const },
  { label: '7 Days', value: 7, unit: 'day' as const },
  { label: '30 Days', value: 30, unit: 'day' as const },
];

// Bucket options based on time range
const BUCKET_OPTIONS = [
  { label: '1 second', value: '1 second' },
  { label: '10 seconds', value: '10 seconds' },
  { label: '1 minute', value: '1 minute' },
  { label: '5 minutes', value: '5 minutes' },
  { label: '15 minutes', value: '15 minutes' },
  { label: '1 hour', value: '1 hour' },
  { label: '1 day', value: '1 day' },
];

const AGGREGATE_OPTIONS: { label: string; value: AggregateFunction }[] = [
  { label: 'Average', value: 'avg' },
  { label: 'Minimum', value: 'min' },
  { label: 'Maximum', value: 'max' },
  { label: 'First', value: 'first' },
  { label: 'Last', value: 'last' },
];

export default function Trends() {
  // Selected tags
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [availableTags, setAvailableTags] = useState<string[]>([]);
  const [isLoadingTags, setIsLoadingTags] = useState(true);

  // Time range
  const [selectedRange, setSelectedRange] = useState(TIME_RANGES[2]); // 8 hours default
  const [customRange, setCustomRange] = useState(false);
  const [startTime, setStartTime] = useState<Date>(() => {
    const d = new Date();
    d.setHours(d.getHours() - 8);
    return d;
  });
  const [endTime, setEndTime] = useState<Date>(() => new Date());

  // Aggregation settings
  const [bucket, setBucket] = useState('1 minute');
  const [aggregate, setAggregate] = useState<AggregateFunction>('avg');

  // Auto-refresh
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  // Tag selection dropdown
  const [showTagDropdown, setShowTagDropdown] = useState(false);
  const [tagSearch, setTagSearch] = useState('');

  // Fetch available tags
  useEffect(() => {
    const fetchTags = async () => {
      setIsLoadingTags(true);
      try {
        const response = await historyApi.getAvailableTags();
        setAvailableTags(response.tags);
      } catch (err) {
        console.error('Failed to fetch available tags:', err);
      } finally {
        setIsLoadingTags(false);
      }
    };
    fetchTags();
  }, []);

  // Computed time range
  const timeRange = useMemo(() => {
    if (customRange) {
      return { start: startTime, end: endTime };
    }

    const end = new Date();
    const start = new Date();

    if (selectedRange.unit === 'hour') {
      start.setHours(start.getHours() - selectedRange.value);
    } else {
      start.setDate(start.getDate() - selectedRange.value);
    }

    return { start, end };
  }, [customRange, startTime, endTime, selectedRange, refreshKey]);

  // Auto-suggest bucket based on range
  useEffect(() => {
    if (customRange) return;

    const hours = selectedRange.unit === 'hour' ? selectedRange.value : selectedRange.value * 24;

    if (hours <= 1) {
      setBucket('1 second');
    } else if (hours <= 4) {
      setBucket('10 seconds');
    } else if (hours <= 8) {
      setBucket('1 minute');
    } else if (hours <= 24) {
      setBucket('5 minutes');
    } else if (hours <= 168) {
      // 7 days
      setBucket('15 minutes');
    } else {
      setBucket('1 hour');
    }
  }, [selectedRange, customRange]);

  // Handle preset time range selection
  const handleRangeSelect = (range: (typeof TIME_RANGES)[0]) => {
    setSelectedRange(range);
    setCustomRange(false);
    setRefreshKey((k) => k + 1);
  };

  // Handle tag selection
  const handleTagSelect = (tag: string) => {
    if (!selectedTags.includes(tag)) {
      setSelectedTags([...selectedTags, tag]);
    }
    setShowTagDropdown(false);
    setTagSearch('');
  };

  // Handle tag removal
  const handleTagRemove = (tag: string) => {
    setSelectedTags(selectedTags.filter((t) => t !== tag));
  };

  // Manual refresh
  const handleRefresh = () => {
    setEndTime(new Date());
    setRefreshKey((k) => k + 1);
  };

  // Filtered tags for dropdown
  const filteredTags = useMemo(() => {
    const search = tagSearch.toLowerCase();
    return availableTags.filter(
      (tag) =>
        !selectedTags.includes(tag) && (search === '' || tag.toLowerCase().includes(search))
    );
  }, [availableTags, selectedTags, tagSearch]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
            <TrendingUp className="w-6 h-6 text-accent-primary" />
            Trends
          </h1>
          <p className="text-text-secondary text-sm mt-1">Historical tag data visualization</p>
        </div>

        <div className="flex items-center gap-3">
          {/* Auto-refresh toggle */}
          <label className="flex items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-border-default bg-bg-tertiary text-accent-primary focus:ring-accent-primary"
            />
            Auto-refresh
          </label>

          {/* Refresh button */}
          <button onClick={handleRefresh} className="btn-secondary flex items-center gap-2">
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Controls */}
      <div className="card p-4">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Tag selection */}
          <div>
            <label className="block text-sm text-text-secondary mb-2">Tags</label>
            <div className="relative">
              {/* Selected tags */}
              <div className="flex flex-wrap gap-2 mb-2">
                {selectedTags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 bg-accent-primary/20 text-accent-primary px-2 py-1 rounded text-sm"
                  >
                    {tag}
                    <button
                      onClick={() => handleTagRemove(tag)}
                      className="hover:text-status-alarm"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>

              {/* Add tag button/dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowTagDropdown(!showTagDropdown)}
                  className="btn-secondary w-full flex items-center justify-between"
                  disabled={isLoadingTags}
                >
                  <span className="flex items-center gap-2">
                    <Plus className="w-4 h-4" />
                    Add Tag
                  </span>
                  <ChevronDown className="w-4 h-4" />
                </button>

                {showTagDropdown && (
                  <div className="absolute z-20 mt-1 w-full bg-bg-elevated border border-border-default rounded-lg shadow-lg max-h-60 overflow-auto">
                    <input
                      type="text"
                      value={tagSearch}
                      onChange={(e) => setTagSearch(e.target.value)}
                      placeholder="Search tags..."
                      className="input w-full border-0 border-b border-border-default rounded-none focus:ring-0"
                      autoFocus
                    />
                    {filteredTags.length > 0 ? (
                      filteredTags.map((tag) => (
                        <button
                          key={tag}
                          onClick={() => handleTagSelect(tag)}
                          className="w-full text-left px-3 py-2 hover:bg-bg-tertiary text-text-primary text-sm"
                        >
                          {tag}
                        </button>
                      ))
                    ) : (
                      <div className="px-3 py-2 text-text-muted text-sm">
                        {isLoadingTags ? 'Loading...' : 'No tags available'}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Time range */}
          <div>
            <label className="block text-sm text-text-secondary mb-2">Time Range</label>
            <div className="flex flex-wrap gap-2">
              {TIME_RANGES.map((range) => (
                <button
                  key={range.label}
                  onClick={() => handleRangeSelect(range)}
                  className={`px-3 py-1 rounded text-sm transition-colors ${
                    !customRange && selectedRange.label === range.label
                      ? 'bg-accent-primary text-white'
                      : 'bg-bg-tertiary text-text-secondary hover:bg-bg-elevated'
                  }`}
                >
                  {range.label}
                </button>
              ))}
              <button
                onClick={() => setCustomRange(true)}
                className={`px-3 py-1 rounded text-sm transition-colors ${
                  customRange
                    ? 'bg-accent-primary text-white'
                    : 'bg-bg-tertiary text-text-secondary hover:bg-bg-elevated'
                }`}
              >
                <Calendar className="w-4 h-4 inline-block mr-1" />
                Custom
              </button>
            </div>

            {/* Custom range inputs */}
            {customRange && (
              <div className="mt-3 grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-text-muted">Start</label>
                  <input
                    type="datetime-local"
                    value={startTime.toISOString().slice(0, 16)}
                    onChange={(e) => setStartTime(new Date(e.target.value))}
                    className="input w-full text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs text-text-muted">End</label>
                  <input
                    type="datetime-local"
                    value={endTime.toISOString().slice(0, 16)}
                    onChange={(e) => setEndTime(new Date(e.target.value))}
                    className="input w-full text-sm"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Aggregation settings */}
          <div>
            <label className="block text-sm text-text-secondary mb-2">Aggregation</label>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs text-text-muted">Bucket</label>
                <select
                  value={bucket}
                  onChange={(e) => setBucket(e.target.value)}
                  className="input w-full text-sm"
                >
                  {BUCKET_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-text-muted">Function</label>
                <select
                  value={aggregate}
                  onChange={(e) => setAggregate(e.target.value as AggregateFunction)}
                  className="input w-full text-sm"
                >
                  {AGGREGATE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="card p-4">
        {selectedTags.length > 0 ? (
          <TrendChart
            key={refreshKey}
            tags={selectedTags}
            startTime={timeRange.start}
            endTime={timeRange.end}
            bucket={bucket}
            aggregate={aggregate}
            refreshInterval={autoRefresh ? 5000 : 0}
            height={400}
          />
        ) : (
          <div className="flex flex-col items-center justify-center py-16 text-text-muted">
            <Clock className="w-12 h-12 mb-4 opacity-50" />
            <p className="text-lg">Select tags to view trends</p>
            <p className="text-sm mt-1">Use the tag selector above to add tags to the chart</p>
          </div>
        )}
      </div>

      {/* Info */}
      <div className="text-xs text-text-muted text-center">
        Data is aggregated using TimescaleDB time_bucket function for efficient querying.
        {selectedTags.length > 0 && (
          <span className="ml-2">
            Showing {bucket} intervals with {aggregate} aggregation.
          </span>
        )}
      </div>
    </div>
  );
}
