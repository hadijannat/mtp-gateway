import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  Cog,
  RefreshCw,
  Wifi,
  WifiOff,
  Thermometer,
  ToggleLeft,
} from 'lucide-react';
import { useTagsStore, useServicesStore, useAlarmsStore } from '../store';
import { useWebSocket } from '../hooks/useWebSocket';
import TagValueDisplay from '../components/tags/TagValueDisplay';
import ServiceStatusCard from '../components/services/ServiceStatusCard';

export default function Dashboard() {
  const { tagList, fetchTags, updateTag, isLoading: tagsLoading } = useTagsStore();
  const { serviceList, fetchServices, updateServiceState, isLoading: servicesLoading } = useServicesStore();
  const { activeCount, unacknowledgedCount, fetchAlarms } = useAlarmsStore();

  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // WebSocket connection with handlers
  const { isConnected, connectionState } = useWebSocket({
    onTagUpdate: updateTag,
    onStateChange: updateServiceState,
    onAlarm: (payload) => {
      // Refresh alarms when we receive alarm events
      if (payload.action === 'raised') {
        fetchAlarms();
      }
    },
  });

  // Initial data fetch
  useEffect(() => {
    const loadData = async () => {
      await Promise.all([fetchTags(), fetchServices(), fetchAlarms()]);
      setLastRefresh(new Date());
    };
    loadData();
  }, [fetchTags, fetchServices, fetchAlarms]);

  // Manual refresh
  const handleRefresh = async () => {
    await Promise.all([fetchTags(), fetchServices(), fetchAlarms()]);
    setLastRefresh(new Date());
  };

  // Group tags by type for display
  const analogTags = tagList.filter(
    (t) => typeof t.value === 'number' && t.name.includes('_')
  );
  const digitalTags = tagList.filter(
    (t) => typeof t.value === 'boolean'
  );

  const isLoading = tagsLoading || servicesLoading;

  return (
    <div className="space-y-6">
      {/* Header with status */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Dashboard</h1>
          <p className="text-text-secondary text-sm mt-1">
            Real-time process overview
          </p>
        </div>

        <div className="flex items-center gap-4">
          {/* Connection status */}
          <div className="flex items-center gap-2">
            {isConnected ? (
              <>
                <Wifi className="w-4 h-4 text-status-good" />
                <span className="text-sm text-status-good">Live</span>
              </>
            ) : (
              <>
                <WifiOff className="w-4 h-4 text-status-offline" />
                <span className="text-sm text-status-offline capitalize">
                  {connectionState}
                </span>
              </>
            )}
          </div>

          {/* Refresh button */}
          <button
            onClick={handleRefresh}
            disabled={isLoading}
            className="btn-secondary flex items-center gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Tags */}
        <SummaryCard
          icon={Activity}
          label="Process Tags"
          value={tagList.length}
          href="/tags"
          color="accent"
        />

        {/* Services */}
        <SummaryCard
          icon={Cog}
          label="Services"
          value={serviceList.length}
          sublabel={`${serviceList.filter((s) => s.state === 'EXECUTE').length} running`}
          href="/services"
          color="good"
        />

        {/* Active Alarms */}
        <SummaryCard
          icon={AlertTriangle}
          label="Active Alarms"
          value={activeCount}
          sublabel={unacknowledgedCount > 0 ? `${unacknowledgedCount} unack` : undefined}
          href="/alarms"
          color={activeCount > 0 ? 'alarm' : 'good'}
        />

        {/* Connection */}
        <div className="card p-4">
          <div className="flex items-center gap-3">
            <div
              className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                isConnected ? 'bg-status-good/20' : 'bg-status-offline/20'
              }`}
            >
              {isConnected ? (
                <Wifi className="w-5 h-5 text-status-good" />
              ) : (
                <WifiOff className="w-5 h-5 text-status-offline" />
              )}
            </div>
            <div>
              <p className="text-text-secondary text-sm">WebSocket</p>
              <p
                className={`text-lg font-semibold ${
                  isConnected ? 'text-status-good' : 'text-status-offline'
                }`}
              >
                {isConnected ? 'Connected' : 'Disconnected'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Services overview */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-text-primary">Services</h2>
          <Link to="/services" className="text-accent-primary text-sm hover:underline">
            View all
          </Link>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {serviceList.slice(0, 6).map((service) => (
            <ServiceStatusCard key={service.name} service={service} />
          ))}
          {serviceList.length === 0 && !servicesLoading && (
            <div className="card p-4 col-span-full text-center text-text-muted">
              No services configured
            </div>
          )}
        </div>
      </section>

      {/* Tag values */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Analog values */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Thermometer className="w-5 h-5 text-accent-primary" />
            <h2 className="text-lg font-semibold text-text-primary">Analog Values</h2>
          </div>
          <div className="card divide-y divide-border-subtle">
            {analogTags.slice(0, 8).map((tag) => (
              <TagValueDisplay key={tag.name} tag={tag} />
            ))}
            {analogTags.length === 0 && !tagsLoading && (
              <div className="p-4 text-center text-text-muted">
                No analog tags
              </div>
            )}
          </div>
        </section>

        {/* Digital values */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <ToggleLeft className="w-5 h-5 text-accent-primary" />
            <h2 className="text-lg font-semibold text-text-primary">Digital Values</h2>
          </div>
          <div className="card divide-y divide-border-subtle">
            {digitalTags.slice(0, 8).map((tag) => (
              <TagValueDisplay key={tag.name} tag={tag} />
            ))}
            {digitalTags.length === 0 && !tagsLoading && (
              <div className="p-4 text-center text-text-muted">
                No digital tags
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Last refresh */}
      {lastRefresh && (
        <p className="text-xs text-text-muted text-center">
          Last refresh: {lastRefresh.toLocaleTimeString()}
        </p>
      )}
    </div>
  );
}

// Summary card component
interface SummaryCardProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | string;
  sublabel?: string;
  href: string;
  color: 'accent' | 'good' | 'warning' | 'alarm';
}

function SummaryCard({ icon: Icon, label, value, sublabel, href, color }: SummaryCardProps) {
  const colorClasses = {
    accent: 'bg-accent-primary/20 text-accent-primary',
    good: 'bg-status-good/20 text-status-good',
    warning: 'bg-status-warning/20 text-status-warning',
    alarm: 'bg-status-alarm/20 text-status-alarm',
  };

  return (
    <Link to={href} className="card p-4 hover:bg-bg-tertiary/50 transition-colors">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${colorClasses[color]}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div>
          <p className="text-text-secondary text-sm">{label}</p>
          <p className="text-xl font-semibold text-text-primary">{value}</p>
          {sublabel && <p className="text-xs text-text-muted">{sublabel}</p>}
        </div>
      </div>
    </Link>
  );
}
