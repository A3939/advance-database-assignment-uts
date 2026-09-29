import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
export default defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    ".next/**",
    ".next-agent/**",
    ".next-regions/**",
    ".next-analysis/**",
    ".playwright-cli/**",
    "output/playwright/**",
    "public/vendor/**",
    "next-env.d.ts",
    "artifacts/**",
    "test-results/**",
    "playwright-report/**",
  ]),
]);
