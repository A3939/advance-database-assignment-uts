import type { Source, Filters } from "./contracts";
export const DEFAULT_FILTERS: Filters = {
  source: "All",
  dateRange: { from: "2020-01-01", to: "2024-12-31" },
  datasetVersion: "demo-v1.0",
  batchId: "demo-all-v1",
};
export const FIXTURES = {
  NSW: {
    annual: [3215, 3482, 3911, 4028, 3784],
    fatal: 172,
    deaths: 188,
    casualties: 8640,
    severity: [172, 1308, 3000, 4160, 9780],
    labels: [
      "Fatal",
      "Serious injury",
      "Moderate injury",
      "Minor / other injury",
      "Towaway",
    ],
    regions: [
      { id: "15900", name: "Newcastle", coordinates: [151.78, -32.93] },
      { id: "17200", name: "Sydney", coordinates: [151.21, -33.87] },
      { id: "18450", name: "Wollongong", coordinates: [150.89, -34.43] },
    ],
    bounds: [
      [140.8, -37.6],
      [153.7, -28.0],
    ],
    title: "New South Wales",
  },
  VIC: {
    annual: [1820, 1940, 2110, 2230, 2080],
    fatal: 96,
    deaths: 105,
    casualties: 4120,
    severity: [96, 2800, 7284],
    labels: [
      "Fatal accident",
      "Serious injury accident",
      "Other injury accident",
    ],
    regions: [
      { id: "24600", name: "Melbourne", coordinates: [144.96, -37.81] },
      { id: "22750", name: "Geelong", coordinates: [144.36, -38.15] },
      { id: "20570", name: "Ballarat", coordinates: [143.85, -37.56] },
    ],
    bounds: [
      [140.8, -39.2],
      [150.1, -33.8],
    ],
    title: "Victoria",
  },
  QLD: {
    annual: [1650, 1790, 1920, 2050, 1980],
    fatal: 110,
    deaths: 121,
    casualties: 5340,
    severity: [110, 2500, 4100, 2680],
    labels: ["Fatal", "Hospitalisation", "Medical treatment", "Minor injury"],
    regions: [
      { id: "31000", name: "Brisbane", coordinates: [153.03, -27.47] },
      { id: "33430", name: "Gold Coast", coordinates: [153.4, -28.0] },
      { id: "37010", name: "Townsville", coordinates: [146.82, -19.26] },
    ],
    bounds: [
      [137.8, -29.3],
      [153.7, -10.5],
    ],
    title: "Queensland",
  },
} satisfies Record<
  Source,
  {
    annual: number[];
    fatal: number;
    deaths: number;
    casualties: number;
    severity: number[];
    labels: string[];
    regions: { id: string; name: string; coordinates: [number, number] }[];
    bounds: [[number, number], [number, number]];
    title: string;
  }
>;
/** Largest-remainder apportionment keeps every subtotal exactly reconcilable. */
export function allocate(total: number, weights: number[]): number[] {
  const sum = weights.reduce((a, b) => a + b, 0);
  if (!sum) return weights.map(() => 0);
  const exact = weights.map((w) => (total * w) / sum),
    result = exact.map(Math.floor);
  const order = exact
    .map((n, i) => ({ i, r: n - result[i] }))
    .sort((a, b) => b.r - a.r || a.i - b.i);
  const remainder = total - result.reduce((a, b) => a + b, 0);
  for (let i = 0; i < remainder; i++) result[order[i].i]++;
  return result;
}
// Dates represent months, never fabricated daily granularity.
export const MONTHLY = Object.fromEntries(
  (Object.keys(FIXTURES) as Source[]).map((source) => {
    const f = FIXTURES[source as keyof typeof FIXTURES];
    const crashes = f.annual.flatMap((n) =>
      allocate(n, [8, 7, 9, 8, 8, 7, 8, 9, 8, 9, 9, 10]),
    );
    let capacity = [...crashes];
    const severity = f.severity.map((total, index) => {
      const values =
        index === f.severity.length - 1 ? capacity : allocate(total, capacity);
      capacity = capacity.map((n, i) => n - values[i]);
      return values;
    });
    const deaths = allocate(f.deaths, crashes),
      casualties = allocate(f.casualties, crashes);
    return [
      source,
      crashes.map((n, i) => ({
        period: `${2020 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`,
        crashes: n,
        fatalCrashes: severity[0][i],
        livesLost: deaths[i],
        casualties: casualties[i],
        severity: severity.map((values) => values[i]),
      })),
    ];
  }),
) as Record<
  Source,
  {
    period: string;
    crashes: number;
    fatalCrashes: number;
    livesLost: number;
    casualties: number;
    severity: number[];
  }[]
>;
