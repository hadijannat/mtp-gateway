import { Link } from 'react-router-dom';
import { Lock, ChevronRight } from 'lucide-react';
import type { ServiceResponse, ServiceState } from '../../types';

interface ServiceStatusCardProps {
  service: ServiceResponse;
  showLink?: boolean;
}

// State colors matching industrial standards
const STATE_COLORS: Record<ServiceState, string> = {
  UNDEFINED: 'bg-status-offline',
  IDLE: 'bg-packml-idle',
  STARTING: 'bg-packml-starting',
  EXECUTE: 'bg-packml-execute',
  COMPLETING: 'bg-packml-completing',
  COMPLETE: 'bg-packml-complete',
  RESETTING: 'bg-packml-resetting',
  HOLDING: 'bg-packml-holding',
  HELD: 'bg-packml-held',
  UNHOLDING: 'bg-packml-unholding',
  SUSPENDING: 'bg-packml-suspending',
  SUSPENDED: 'bg-packml-suspended',
  UNSUSPENDING: 'bg-packml-unsuspending',
  STOPPING: 'bg-packml-stopping',
  STOPPED: 'bg-packml-stopped',
  ABORTING: 'bg-packml-aborting',
  ABORTED: 'bg-packml-aborted',
  CLEARING: 'bg-packml-clearing',
};

const STATE_TEXT_COLORS: Record<ServiceState, string> = {
  UNDEFINED: 'text-status-offline',
  IDLE: 'text-packml-idle',
  STARTING: 'text-packml-starting',
  EXECUTE: 'text-packml-execute',
  COMPLETING: 'text-packml-completing',
  COMPLETE: 'text-packml-complete',
  RESETTING: 'text-packml-resetting',
  HOLDING: 'text-packml-holding',
  HELD: 'text-packml-held',
  UNHOLDING: 'text-packml-unholding',
  SUSPENDING: 'text-packml-suspending',
  SUSPENDED: 'text-packml-suspended',
  UNSUSPENDING: 'text-packml-unsuspending',
  STOPPING: 'text-packml-stopping',
  STOPPED: 'text-packml-stopped',
  ABORTING: 'text-packml-aborting',
  ABORTED: 'text-packml-aborted',
  CLEARING: 'text-packml-clearing',
};

// Transitional states that indicate something is happening
const TRANSITIONAL_STATES: ServiceState[] = [
  'STARTING',
  'COMPLETING',
  'RESETTING',
  'HOLDING',
  'UNHOLDING',
  'SUSPENDING',
  'UNSUSPENDING',
  'STOPPING',
  'ABORTING',
  'CLEARING',
];

export default function ServiceStatusCard({ service, showLink = true }: ServiceStatusCardProps) {
  const isTransitional = TRANSITIONAL_STATES.includes(service.state);
  const stateColor = STATE_COLORS[service.state] ?? 'bg-status-offline';
  const textColor = STATE_TEXT_COLORS[service.state] ?? 'text-status-offline';

  const content = (
    <div className="card p-4">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          {/* Service name */}
          <h3 className="font-semibold text-text-primary truncate">{service.name}</h3>

          {/* Mode and procedure */}
          <div className="flex items-center gap-2 mt-1 text-xs text-text-muted">
            <span className="capitalize">{service.mode.replace('_', ' ')}</span>
            {service.procedure_name && (
              <>
                <span>•</span>
                <span>{service.procedure_name}</span>
              </>
            )}
          </div>
        </div>

        {/* State indicator */}
        <div className="flex items-center gap-2">
          {/* Interlock indicator */}
          {service.interlocked && (
            <div className="w-6 h-6 rounded flex items-center justify-center bg-status-warning/20">
              <Lock className="w-4 h-4 text-status-warning" />
            </div>
          )}

          {/* State badge */}
          <div className="flex items-center gap-2">
            <div
              className={`w-3 h-3 rounded-full ${stateColor} ${
                isTransitional ? 'animate-pulse' : ''
              }`}
            />
            <span className={`text-sm font-medium ${textColor}`}>
              {service.state}
            </span>
          </div>

          {showLink && <ChevronRight className="w-4 h-4 text-text-muted" />}
        </div>
      </div>

      {/* Interlock reason */}
      {service.interlocked && service.interlock_reason && (
        <div className="mt-3 p-2 rounded bg-status-warning/10 border border-status-warning/20">
          <p className="text-xs text-status-warning">
            <Lock className="w-3 h-3 inline mr-1" />
            {service.interlock_reason}
          </p>
        </div>
      )}

      {/* State time */}
      {service.state_time && (
        <p className="mt-2 text-xs text-text-muted">
          Since {new Date(service.state_time).toLocaleTimeString()}
        </p>
      )}
    </div>
  );

  if (showLink) {
    return (
      <Link
        to={`/services/${service.name}`}
        className="block hover:ring-2 hover:ring-accent-primary/30 rounded-lg transition-all"
      >
        {content}
      </Link>
    );
  }

  return content;
}
