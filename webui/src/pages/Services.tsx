import { useEffect } from 'react';
import { useServicesStore } from '../store';
import { useWebSocket } from '../hooks/useWebSocket';
import ServiceStatusCard from '../components/services/ServiceStatusCard';
import ServiceCommandPanel from '../components/services/ServiceCommandPanel';
import { RefreshCw, Wifi, WifiOff } from 'lucide-react';

export default function Services() {
  const {
    serviceList,
    fetchServices,
    updateServiceState,
    isLoading,
  } = useServicesStore();

  const { isConnected, connectionState } = useWebSocket({
    onStateChange: updateServiceState,
  });

  useEffect(() => {
    fetchServices();
  }, [fetchServices]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Services</h1>
          <p className="text-text-secondary text-sm mt-1">
            PackML service control and monitoring
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

          <button
            onClick={() => fetchServices()}
            disabled={isLoading}
            className="btn-secondary flex items-center gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Services grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {serviceList.map((service) => (
          <div key={service.name} className="space-y-4">
            <ServiceStatusCard service={service} showLink={false} />
            <ServiceCommandPanel service={service} />
          </div>
        ))}
      </div>

      {/* Empty state */}
      {serviceList.length === 0 && !isLoading && (
        <div className="card p-8 text-center">
          <p className="text-text-secondary">No services configured</p>
          <p className="text-text-muted text-sm mt-2">
            Services will appear here when defined in the gateway configuration.
          </p>
        </div>
      )}

      {/* Loading state */}
      {isLoading && serviceList.length === 0 && (
        <div className="card p-8 text-center">
          <RefreshCw className="w-8 h-8 text-accent-primary animate-spin mx-auto mb-4" />
          <p className="text-text-secondary">Loading services...</p>
        </div>
      )}
    </div>
  );
}
