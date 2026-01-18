import { useState, useEffect } from 'react';
import { CheckCircle, AlertCircle, HelpCircle, WifiOff } from 'lucide-react';
import type { TagValue, TagQuality } from '../../types';

interface TagValueDisplayProps {
  tag: TagValue;
  showTimestamp?: boolean;
  compact?: boolean;
}

export default function TagValueDisplay({
  tag,
  showTimestamp = false,
  compact = false,
}: TagValueDisplayProps) {
  const [isUpdating, setIsUpdating] = useState(false);
  const [prevValue, setPrevValue] = useState(tag.value);

  // Flash animation when value changes
  useEffect(() => {
    if (tag.value !== prevValue) {
      setIsUpdating(true);
      setPrevValue(tag.value);
      const timer = setTimeout(() => setIsUpdating(false), 300);
      return () => clearTimeout(timer);
    }
  }, [tag.value, prevValue]);

  const getQualityIcon = (quality: TagQuality) => {
    switch (quality) {
      case 'good':
        return <CheckCircle className="w-4 h-4 text-status-good" />;
      case 'uncertain':
        return <HelpCircle className="w-4 h-4 text-status-uncertain" />;
      case 'bad':
        return <AlertCircle className="w-4 h-4 text-status-alarm" />;
      case 'offline':
        return <WifiOff className="w-4 h-4 text-status-offline" />;
    }
  };

  const getQualityBadgeClass = (quality: TagQuality) => {
    switch (quality) {
      case 'good':
        return 'badge-good';
      case 'uncertain':
        return 'badge-uncertain';
      case 'bad':
        return 'badge-alarm';
      case 'offline':
        return 'badge-offline';
    }
  };

  const formatValue = (value: TagValue['value']): string => {
    if (value === null) return '---';
    if (typeof value === 'boolean') return value ? 'ON' : 'OFF';
    if (typeof value === 'number') {
      // Format with appropriate precision
      if (Number.isInteger(value)) return value.toString();
      return value.toFixed(2);
    }
    return String(value);
  };

  const formatTimestamp = (timestamp: string): string => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
  };

  if (compact) {
    return (
      <div className="flex items-center justify-between py-2 px-3">
        <span className="text-text-secondary text-sm truncate">{tag.name}</span>
        <div className="flex items-center gap-2">
          <span
            className={`font-mono text-text-primary ${isUpdating ? 'value-updating' : ''}`}
          >
            {formatValue(tag.value)}
            {tag.unit && <span className="text-text-muted text-xs ml-1">{tag.unit}</span>}
          </span>
          {getQualityIcon(tag.quality)}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between py-3 px-4">
      <div className="min-w-0 flex-1">
        <p className="text-text-primary font-medium truncate">{tag.name}</p>
        {tag.description && (
          <p className="text-text-muted text-xs truncate">{tag.description}</p>
        )}
      </div>

      <div className="flex items-center gap-3 ml-4">
        {/* Value */}
        <div
          className={`text-right ${isUpdating ? 'value-updating' : ''}`}
        >
          <span className="font-mono text-lg text-text-primary">
            {formatValue(tag.value)}
          </span>
          {tag.unit && (
            <span className="text-text-muted text-sm ml-1">{tag.unit}</span>
          )}
          {showTimestamp && (
            <p className="text-text-muted text-xs">{formatTimestamp(tag.timestamp)}</p>
          )}
        </div>

        {/* Quality badge */}
        <span
          className={`px-2 py-1 rounded text-xs font-medium ${getQualityBadgeClass(tag.quality)}`}
        >
          {tag.quality.toUpperCase()}
        </span>
      </div>
    </div>
  );
}
