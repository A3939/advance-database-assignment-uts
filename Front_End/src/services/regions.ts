import regions from './region-catalog.json';
/** Only the immutable baseline has an admitted ABS LGA crosswalk. */
export function regionsForSource(source:string):{id:string;name:string}[] {
  return regions[source as keyof typeof regions] || [];
}
