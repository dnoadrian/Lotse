import type { Service, ServiceStatus } from "../api/types";
import { STATUS_META, STATUS_ORDER, isServiceStatus } from "../lib/mappings";

export function StatusSelect({
  service,
  onChange,
  compact = false,
}: {
  service: Service;
  onChange: (s: Service, status: ServiceStatus) => void;
  compact?: boolean;
}) {
  return (
    <label className={`status-label${compact ? " status-label-compact" : ""}`}>
      <span className="sr-only">Status für {service.name}</span>
      <select
        className="status-select"
        data-status={service.status}
        value={service.status}
        onChange={(e) => {
          const v = e.target.value;
          if (isServiceStatus(v)) onChange(service, v);
        }}
      >
        {STATUS_ORDER.map((s) => (
          <option key={s} value={s}>
            {STATUS_META[s].label}
          </option>
        ))}
      </select>
    </label>
  );
}
