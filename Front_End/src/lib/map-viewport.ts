import type { Geometry, Position } from "geojson";
import type { MapData } from "../services/contracts";

type Bounds = MapData["bounds"];
type Level = "country" | "state";
export interface MapPadding {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

const MAX_MERCATOR_LATITUDE = 85.0511287798066;
const radians = (degrees: number) => (degrees * Math.PI) / 180;
const dimension = (value: number) =>
  Number.isFinite(value) ? Math.max(1, value) : 1;

/** Spherical Mercator, with north-positive y before screen inversion. */
function mercator(position: Position): [number, number] {
  const latitude = Math.max(
    -MAX_MERCATOR_LATITUDE,
    Math.min(MAX_MERCATOR_LATITUDE, position[1]),
  );
  return [
    radians(position[0]),
    Math.log(Math.tan(Math.PI / 4 + radians(latitude) / 2)),
  ];
}

function extent(bounds: Bounds) {
  const southwest = mercator(bounds[0]),
    northeast = mercator(bounds[1]);
  return {
    west: southwest[0],
    north: northeast[1],
    width: Math.max(Number.EPSILON, northeast[0] - southwest[0]),
    height: Math.max(Number.EPSILON, northeast[1] - southwest[1]),
  };
}

/** Leave a drawable pixel even while an element is collapsed during layout. */
function constrainedPadding(
  padding: MapPadding,
  width: number,
  height: number,
): MapPadding {
  const horizontal = Math.min(
    1,
    Math.max(0, width - 1) / (padding.left + padding.right),
  );
  const vertical = Math.min(
    1,
    Math.max(0, height - 1) / (padding.top + padding.bottom),
  );
  return {
    top: padding.top * vertical,
    bottom: padding.bottom * vertical,
    left: padding.left * horizontal,
    right: padding.right * horizontal,
  };
}

/** One fit policy shared by WebGL, resize/reset and the SVG fallback. */
export function mapPadding(
  bounds: Bounds,
  width: number,
  height: number,
  level: Level,
  reserved: Partial<MapPadding> = {},
): MapPadding {
  const w = dimension(width),
    h = dimension(height);
  const reserve = (padding: MapPadding) => constrainedPadding({
    top: Math.max(padding.top, reserved.top || 0),
    bottom: Math.max(padding.bottom, reserved.bottom || 0),
    left: Math.max(padding.left, reserved.left || 0),
    right: Math.max(padding.right, reserved.right || 0),
  }, w, h);
  if (level === "state")
    return reserve(
      { top: 12, bottom: 64, left: 12, right: Math.min(150, w * 0.27) },
    );
  if (w < 500)
    return reserve({ top: 8, bottom: 56, left: 8, right: 12 });

  const padding = reserve(
    { top: 8, bottom: 32, left: 4, right: 24 },
  );
  const box = extent(bounds);
  const innerWidth = w - padding.left - padding.right;
  const innerHeight = h - padding.top - padding.bottom;
  const scale = Math.min(innerWidth / box.width, innerHeight / box.height);
  // Consume only spare space: the geographic scale stays unchanged.
  const spareWidth = Math.max(0, innerWidth - box.width * scale);
  const spareHeight = Math.max(0, innerHeight - box.height * scale);
  return {
    ...padding,
    right: padding.right + spareWidth * 0.65,
    top: padding.top + spareHeight * 0.4,
  };
}

function projection(
  bounds: Bounds,
  width: number,
  height: number,
  level: Level,
  reserved: Partial<MapPadding> = {},
) {
  const w = dimension(width),
    h = dimension(height);
  const padding = mapPadding(bounds, w, h, level, reserved),
    box = extent(bounds);
  const innerWidth = w - padding.left - padding.right;
  const innerHeight = h - padding.top - padding.bottom;
  const scale = Math.min(innerWidth / box.width, innerHeight / box.height);
  const left = padding.left + (innerWidth - box.width * scale) / 2;
  const top = padding.top + (innerHeight - box.height * scale) / 2;
  return (position: Position): [number, number] => {
    const point = mercator(position);
    return [
      left + (point[0] - box.west) * scale,
      top + (box.north - point[1]) * scale,
    ];
  };
}

/** Positions beyond the fitted bounds remain beyond them; no data is clipped. */
export function projectMapPoint(
  position: Position,
  bounds: Bounds,
  width: number,
  height: number,
  level: Level,
  reserved: Partial<MapPadding> = {},
): [number, number] {
  return projection(bounds, width, height, level, reserved)(position);
}

/** Polygon rings keep their original order and coordinates, including islands. */
export function mapSvgPath(
  geometry: Geometry,
  bounds: Bounds,
  width: number,
  height: number,
  level: Level,
  reserved: Partial<MapPadding> = {},
): string {
  const project = projection(bounds, width, height, level, reserved);
  const rings =
    geometry.type === "Polygon"
      ? geometry.coordinates
      : geometry.type === "MultiPolygon"
        ? geometry.coordinates.flatMap((polygon) => polygon)
        : [];
  return rings
    .filter((ring) => ring.length > 0)
    .map((ring) => {
      const points = ring.map((position) =>
        project(position)
          .map((value) => value.toFixed(2))
          .join(","),
      );
      return `M${points.join("L")}Z`;
    })
    .join("");
}
