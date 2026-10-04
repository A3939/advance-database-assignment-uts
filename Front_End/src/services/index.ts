import type { ArsiaService } from "./contracts";
import { httpProvider } from "./http-provider";
/** The application reads real project aggregates through its local API. */
export const arsia: ArsiaService = httpProvider;
export { DEFAULT_FILTERS } from "./config";
