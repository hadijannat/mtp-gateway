import { useState } from 'react';
import {
  Play,
  Square,
  Pause,
  RotateCcw,
  AlertOctagon,
  Trash2,
  Loader2,
} from 'lucide-react';
import { useServicesStore, getValidCommands } from '../../store';
import type { ServiceCommand, ServiceResponse } from '../../types';

interface ServiceCommandPanelProps {
  service: ServiceResponse;
}

// Command configurations
const COMMANDS: {
  command: ServiceCommand;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  style: string;
  confirmRequired?: boolean;
}[] = [
  {
    command: 'START',
    label: 'Start',
    icon: Play,
    style: 'btn-primary',
  },
  {
    command: 'STOP',
    label: 'Stop',
    icon: Square,
    style: 'btn-warning',
  },
  {
    command: 'HOLD',
    label: 'Hold',
    icon: Pause,
    style: 'btn-secondary',
  },
  {
    command: 'UNHOLD',
    label: 'Unhold',
    icon: Play,
    style: 'btn-secondary',
  },
  {
    command: 'SUSPEND',
    label: 'Suspend',
    icon: Pause,
    style: 'btn-secondary',
  },
  {
    command: 'UNSUSPEND',
    label: 'Unsuspend',
    icon: Play,
    style: 'btn-secondary',
  },
  {
    command: 'ABORT',
    label: 'Abort',
    icon: AlertOctagon,
    style: 'btn-danger',
    confirmRequired: true,
  },
  {
    command: 'CLEAR',
    label: 'Clear',
    icon: Trash2,
    style: 'btn-secondary',
  },
  {
    command: 'RESET',
    label: 'Reset',
    icon: RotateCcw,
    style: 'btn-secondary',
  },
];

export default function ServiceCommandPanel({ service }: ServiceCommandPanelProps) {
  const { sendCommand, commandPending } = useServicesStore();
  const [confirmCommand, setConfirmCommand] = useState<ServiceCommand | null>(null);
  const [selectedProcedure, setSelectedProcedure] = useState<number | undefined>(
    service.procedures.find((p) => p.is_default)?.id
  );

  const validCommands = getValidCommands(service.state);
  const isPending = commandPending === service.name;

  const handleCommand = async (command: ServiceCommand) => {
    const config = COMMANDS.find((c) => c.command === command);

    // Check if confirmation required
    if (config?.confirmRequired && confirmCommand !== command) {
      setConfirmCommand(command);
      return;
    }

    setConfirmCommand(null);
    await sendCommand(service.name, command, selectedProcedure);
  };

  const isCommandAvailable = (command: ServiceCommand): boolean => {
    // Check if command is valid for current state
    if (!validCommands.includes(command)) return false;

    // Check interlock for START/UNHOLD
    if (service.interlocked && (command === 'START' || command === 'UNHOLD')) {
      return false;
    }

    return true;
  };

  // Filter to only show relevant commands
  const availableCommands = COMMANDS.filter((cmd) =>
    validCommands.includes(cmd.command)
  );

  return (
    <div className="card p-4">
      <h4 className="text-sm font-medium text-text-secondary mb-3">Commands</h4>

      {/* Procedure selector (only for START) */}
      {service.procedures.length > 1 && validCommands.includes('START') && (
        <div className="mb-4">
          <label className="block text-xs text-text-muted mb-1">Procedure</label>
          <select
            value={selectedProcedure ?? ''}
            onChange={(e) => setSelectedProcedure(Number(e.target.value) || undefined)}
            className="input text-sm w-full"
          >
            {service.procedures.map((proc) => (
              <option key={proc.id} value={proc.id}>
                {proc.name} {proc.is_default ? '(default)' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Command buttons */}
      <div className="flex flex-wrap gap-2">
        {availableCommands.map(({ command, label, icon: Icon, style }) => {
          const available = isCommandAvailable(command);
          const isConfirming = confirmCommand === command;

          return (
            <button
              key={command}
              onClick={() => handleCommand(command)}
              disabled={!available || isPending}
              className={`${style} flex items-center gap-2 text-sm ${
                isConfirming ? 'ring-2 ring-offset-2 ring-offset-bg-secondary ring-white' : ''
              }`}
            >
              {isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Icon className="w-4 h-4" />
              )}
              {isConfirming ? 'Confirm?' : label}
            </button>
          );
        })}

        {availableCommands.length === 0 && (
          <p className="text-text-muted text-sm">
            No commands available in {service.state} state
          </p>
        )}
      </div>

      {/* Cancel confirmation */}
      {confirmCommand && (
        <button
          onClick={() => setConfirmCommand(null)}
          className="mt-2 text-xs text-text-muted hover:text-text-secondary"
        >
          Cancel
        </button>
      )}

      {/* Interlock warning */}
      {service.interlocked && (
        <p className="mt-3 text-xs text-status-warning">
          Service is interlocked - START and UNHOLD are blocked
        </p>
      )}
    </div>
  );
}
