import { copyFile, mkdir } from "node:fs/promises";
// MapLibre 6 module workers import the adjacent shared bundle. Serve both locally.
await mkdir(new URL("../public/vendor/maplibre/", import.meta.url), {
  recursive: true,
});
for (const file of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  await copyFile(
    new URL(`../node_modules/maplibre-gl/dist/${file}`, import.meta.url),
    new URL(`../public/vendor/maplibre/${file}`, import.meta.url),
  );
}
await copyFile(
  new URL("../node_modules/maplibre-gl/LICENSE.txt", import.meta.url),
  new URL("../public/vendor/maplibre/LICENSE.txt", import.meta.url),
);
