import type { NextConfig } from "next";
const config: NextConfig = {
  // Isolate parallel local previews without touching another server's build.
  distDir: process.env.ARSIA_NEXT_DIST_DIR || ".next",
  devIndicators: false,
  serverExternalPackages: ["playwright-core"],
  turbopack: { root: process.cwd() },
};
export default config;
