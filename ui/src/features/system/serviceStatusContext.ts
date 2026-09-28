import { createContext, useContext } from "react";

import type { ServiceSnapshot } from "./api";

export interface ServiceStatus extends ServiceSnapshot {
  refresh: () => void;
}

export const ServiceStatusContext = createContext<ServiceStatus | null>(null);

export function useServiceStatus(): ServiceStatus {
  const status = useContext(ServiceStatusContext);
  if (!status) throw new Error("useServiceStatus phải nằm trong <ServiceStatusProvider>");
  return status;
}
