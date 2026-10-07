import type { Availability, Source } from "./contracts";

export interface SpeedZoneBand { id: string; label: string }
export interface SpeedZoneValue {
  band: string;
  crashes: number;
  fatalCrashes: number;
  fatalKnown: number;
  /** Percent of ALL recorded events in this source/band; null if unknown/empty. */
  share: number | null;
}
export interface SpeedZoneGroup {
  source: Source;
  field: string;
  availability: Availability;
  reason: string | null;
  rows: SpeedZoneValue[];
  excluded: { nativeValue: string; crashes: number; fatalCrashes: number }[];
}
export interface SpeedZoneData {
  bands: SpeedZoneBand[];
  groups: SpeedZoneGroup[];
  reason: string | null;
}
