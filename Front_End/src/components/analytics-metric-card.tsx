"use client";

import { Info, type LucideIcon } from "lucide-react";
import styles from "./analytics.module.css";

/** Single-source values use the same header and typography as the All cards. */
export default function AnalyticsMetricCard({ label, value, Icon, onDefinition, valueTestId, compact, areaName, disabled }: {
  label: string;
  value: string;
  Icon: LucideIcon;
  onDefinition: () => void;
  valueTestId?: string;
  compact?: boolean;
  areaName?: boolean;
  disabled?: boolean;
}) {
  return <article className="panel metric-card">
    <div className="metric-label">
      <Icon size={25} strokeWidth={1.5} aria-hidden="true"/>
      <span>{label}</span>
      <button className="info-button" aria-label={`${label} definition`} onClick={onDefinition} disabled={disabled}>
        <Info size={16}/>
      </button>
    </div>
    <strong data-testid={valueTestId} className={`${styles.singleMetricValue} ${compact ? styles.singleCompactValue : ""} ${areaName ? styles.singleAreaValue : ""}`}>{value}</strong>
  </article>;
}
