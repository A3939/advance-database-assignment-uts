/** Integer event counts: colour band k covers floor((k−1)max/7)+1 … floor(k max/7). */
export function mapCountBand(count: number | undefined, maximum: number): number | null {
  if (count === undefined) return null;
  if (count === 0) return 0;
  return Math.max(1, Math.min(7, Math.ceil((count * 7) / Math.max(1, maximum))));
}
export function mapCountBins(maximum: number): { band: number; from: number; to: number }[] {
  if (!Number.isSafeInteger(maximum) || maximum < 0) throw new Error("Map maximum must be a non-negative integer.");
  return Array.from({ length: 7 }, (_, index) => ({
    band: index + 1,
    from: Math.floor((index * maximum) / 7) + 1,
    to: Math.floor(((index + 1) * maximum) / 7),
  })).filter(bin => bin.from <= bin.to);
}
