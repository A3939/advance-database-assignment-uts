import test from "node:test";
import assert from "node:assert/strict";
import type { Polygon, MultiPolygon } from "geojson";
import type { MapData } from "../src/services/contracts";
import {
  mapPadding,
  mapSvgPath,
  projectMapPoint,
} from "../src/lib/map-viewport";

const COUNTRY: MapData["bounds"] = [
  [111, -44.5],
  [155, -9],
];
const NSW: MapData["bounds"] = [
  [140.8, -37.6],
  [153.7, -28],
];
const close = (a: number, b: number) =>
  assert.ok(Math.abs(a - b) < 1e-8, `${a} differs from ${b}`);

test("mainland extremes and southern Tasmania remain inside desktop, mobile and fullscreen fits", () => {
  const landmarks = [
    [112.9225, -26],
    [153.5522, -28],
    [142.5, -9.1425],
    [146.8, -43.7404],
  ];
  for (const [width, height] of [
    [280, 340],
    [390, 460],
    [780, 610],
    [1920, 1080],
    [2560, 1440],
  ]) {
    const padding = mapPadding(COUNTRY, width, height, "country");
    for (const point of landmarks) {
      const [x, y] = projectMapPoint(point, COUNTRY, width, height, "country");
      assert.ok(x >= padding.left && x <= width - padding.right);
      assert.ok(y >= padding.top && y <= height - padding.bottom);
    }
  }
});

test("equal Mercator distances have equal screen scale on both axes at every aspect ratio", () => {
  const lambda = (130 * Math.PI) / 180;
  const latitude = (-30 * Math.PI) / 180;
  const mercatorY = Math.log(Math.tan(Math.PI / 4 + latitude / 2));
  const delta = 0.02;
  const east = ((lambda + delta) * 180) / Math.PI;
  const north =
    ((2 * Math.atan(Math.exp(mercatorY + delta)) - Math.PI / 2) * 180) /
    Math.PI;
  for (const [width, height] of [
    [280, 340],
    [700, 1100],
    [1920, 720],
  ]) {
    const center = projectMapPoint(
      [130, -30],
      COUNTRY,
      width,
      height,
      "country",
    );
    const eastPoint = projectMapPoint(
      [east, -30],
      COUNTRY,
      width,
      height,
      "country",
    );
    const northPoint = projectMapPoint(
      [130, north],
      COUNTRY,
      width,
      height,
      "country",
    );
    close(eastPoint[0] - center[0], center[1] - northPoint[1]);
    close(eastPoint[1], center[1]);
    close(northPoint[0], center[0]);
  }
});

test("country alignment spends unused space without reducing map scale", () => {
  for (const [width, height] of [
    [1800, 600],
    [650, 1200],
  ]) {
    const padding = mapPadding(COUNTRY, width, height, "country");
    const southwest = projectMapPoint(
      COUNTRY[0],
      COUNTRY,
      width,
      height,
      "country",
    );
    const northeast = projectMapPoint(
      COUNTRY[1],
      COUNTRY,
      width,
      height,
      "country",
    );
    const projectedWidth = northeast[0] - southwest[0];
    const projectedHeight = southwest[1] - northeast[1];
    const mercatorHeight =
      Math.log(Math.tan(Math.PI / 4 - (9 * Math.PI) / 360)) -
      Math.log(Math.tan(Math.PI / 4 - (44.5 * Math.PI) / 360));
    const mercatorWidth = (44 * Math.PI) / 180;
    const originalScale = Math.min(
      (width - 28) / mercatorWidth,
      (height - 40) / mercatorHeight,
    );
    close(projectedWidth, mercatorWidth * originalScale);
    close(projectedHeight, mercatorHeight * originalScale);
    if (width > height) {
      assert.ok(padding.right > 24);
      assert.ok((southwest[0] + northeast[0]) / 2 < width / 2);
    } else {
      assert.ok(padding.top > 8);
      assert.ok((southwest[1] + northeast[1]) / 2 > height / 2);
    }
  }
});

test("mobile controls and state hotspot labels retain their specific safe space", () => {
  assert.deepEqual(mapPadding(COUNTRY, 280, 340, "country"), {
    top: 8,
    bottom: 56,
    left: 8,
    right: 12,
  });
  assert.deepEqual(mapPadding(NSW, 1200, 900, "state"), {
    top: 12,
    bottom: 64,
    left: 12,
    right: 150,
  });
  assert.deepEqual(mapPadding(NSW, 280, 340, "state"), {
    top: 12,
    bottom: 64,
    left: 12,
    right: 75.60000000000001,
  });
  for (const [width, height] of [
    [0, 0],
    [1, 1],
    [20, 10],
    [280, 340],
    [1920, 1080],
  ]) {
    for (const level of ["country", "state"] as const) {
      const padding = mapPadding(COUNTRY, width, height, level);
      assert.ok(
        Object.values(padding).every(
          (value) => Number.isFinite(value) && value >= 0,
        ),
      );
      assert.ok(padding.left + padding.right < Math.max(1, width));
      assert.ok(padding.top + padding.bottom < Math.max(1, height));
      assert.ok(
        projectMapPoint([146.8, -43.7404], COUNTRY, width, height, level).every(
          Number.isFinite,
        ),
      );
    }
  }
});

test("SVG polygons use the same fit, preserve holes and outer islands without mutating geometry", () => {
  const polygon: Polygon = {
    type: "Polygon",
    coordinates: [
      [
        [111, -44.5],
        [155, -44.5],
        [155, -9],
        [111, -44.5],
      ],
      [
        [130, -30],
        [131, -30],
        [131, -29],
        [130, -30],
      ],
    ],
  };
  const multi: MultiPolygon = {
    type: "MultiPolygon",
    coordinates: [
      polygon.coordinates,
      [
        [
          [167.99, -29],
          [168, -29],
          [168, -28],
          [167.99, -29],
        ],
      ],
    ],
  };
  const original = structuredClone(multi);
  const path = mapSvgPath(multi, COUNTRY, 600, 500, "country");
  const first = projectMapPoint(
    polygon.coordinates[0][0],
    COUNTRY,
    600,
    500,
    "country",
  )
    .map((value) => value.toFixed(2))
    .join(",");
  assert.ok(path.startsWith(`M${first}L`));
  assert.equal((path.match(/M/g) || []).length, 3);
  assert.equal((path.match(/Z/g) || []).length, 3);
  assert.ok(projectMapPoint([168, -29], COUNTRY, 600, 500, "country")[0] > 600);
  assert.deepEqual(multi, original);
  assert.equal(
    mapSvgPath(
      { type: "Point", coordinates: [130, -30] },
      COUNTRY,
      600,
      500,
      "country",
    ),
    "",
  );
});
