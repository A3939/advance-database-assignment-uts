"use client";
import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { useTheme } from "./theme-provider";
import { mapSvgPath, projectMapPoint } from "@/lib/map-viewport";
import type { MapData } from "@/services/contracts";
import styles from "./point-grid-map.module.css";

const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
const number = (value: number) => value.toLocaleString("en-AU");
const cellLabel = (longitude: number, latitude: number, count: number) => `${longitude.toFixed(1)}°, ${latitude.toFixed(1)}° · ${number(count)} recorded crashes`;

/** Independent aggregate layer: no ABS join, exact points, or region-filter callback. */
export default function PointGridMap({ data }: { data: MapData }) {
  const grid = data.pointGrid!;
  const { theme } = useTheme();
  const host = useRef<HTMLDivElement>(null), map = useRef<maplibregl.Map | null>(null);
  const displayedBounds = useRef("");
  const context = useRef(data);
  const [ready, setReady] = useState(false), [fallback, setFallback] = useState(false);
  const [boundary, setBoundary] = useState<FeatureCollection>(empty);
  const [readout, setReadout] = useState("");
  const [valuesOpen, setValuesOpen] = useState(false);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const insets = { top: 16, bottom: 170 };
  useEffect(() => { context.current = data; }, [data]);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let disposed = false;
    const controller = new AbortController();
    const observer = new ResizeObserver(() => {
      setSize({ width: element.clientWidth, height: element.clientHeight });
      map.current?.resize();
    });
    observer.observe(element);
    const token = (name: string) => getComputedStyle(element).getPropertyValue(name).trim();
    fetch(data.boundaryUrl, { signal: controller.signal }).then(response => {
      if (!response.ok) throw Error("Boundary reference unavailable");
      return response.json() as Promise<FeatureCollection>;
    }).then(geo => {
      if (disposed) return;
      setBoundary(geo);
      try {
        maplibregl.setWorkerUrl("/vendor/maplibre/maplibre-gl-worker.mjs");
        const instance = new maplibregl.Map({ container: element, attributionControl: false, bounds: context.current.bounds, fitBoundsOptions: { padding: { top: 24, bottom: 180, left: 24, right: 24 } }, style: { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": token("--map-background") } }] } });
        map.current = instance;
        instance.on("error", () => { if (!disposed) setFallback(true); });
        instance.on("load", () => {
          if (disposed) return;
          instance.addSource("grid-boundaries", { type: "geojson", data: geo });
          instance.addLayer({ id: "grid-land", type: "fill", source: "grid-boundaries", paint: { "fill-color": token("--map-land"), "fill-opacity": 0.8 } });
          instance.addLayer({ id: "grid-edges", type: "line", source: "grid-boundaries", paint: { "line-color": token("--map-line"), "line-width": 0.7 } });
          instance.addSource("crash-grid", { type: "geojson", data: empty });
          instance.addLayer({ id: "crash-grid-cells", type: "circle", source: "crash-grid", paint: { "circle-radius": ["get", "radius"], "circle-color": token("--chart-trend"), "circle-opacity": 0.68, "circle-stroke-color": token("--map-background"), "circle-stroke-width": 1 } });
          instance.on("mousemove", "crash-grid-cells", event => {
            const p = event.features?.[0]?.properties;
            if (p) setReadout(cellLabel(Number(p.longitude), Number(p.latitude), Number(p.count)));
            instance.getCanvas().style.cursor = "help";
          });
          instance.on("mouseleave", "crash-grid-cells", () => { setReadout(""); instance.getCanvas().style.cursor = ""; });
          setReady(true);
        });
      } catch { setFallback(true); }
    }).catch(error => { if (!disposed && error.name !== "AbortError") setFallback(true); });
    return () => { disposed = true; controller.abort(); observer.disconnect(); map.current?.remove(); map.current = null; };
  }, [data.boundaryUrl]);
  useEffect(() => {
    const instance = map.current, element = host.current;
    if (!instance || !ready || !element) return;
    const token = (name: string) => getComputedStyle(element).getPropertyValue(name).trim();
    const maximum = Math.max(1, ...grid.cells.map(cell => cell.count));
    const points: FeatureCollection = { type: "FeatureCollection", features: grid.cells.map(cell => ({ type: "Feature", geometry: { type: "Point", coordinates: [cell.longitude, cell.latitude] }, properties: { ...cell, radius: 3 + 15 * Math.sqrt(cell.count / maximum) } })) };
    (instance.getSource("crash-grid") as GeoJSONSource).setData(points);
    instance.setPaintProperty("background", "background-color", token("--map-background"));
    instance.setPaintProperty("grid-land", "fill-color", token("--map-land"));
    instance.setPaintProperty("grid-edges", "line-color", token("--map-line"));
    instance.setPaintProperty("crash-grid-cells", "circle-color", token("--chart-trend"));
    instance.setPaintProperty("crash-grid-cells", "circle-stroke-color", token("--map-background"));
    const boundsKey = JSON.stringify(data.bounds);
    if (displayedBounds.current !== boundsKey) {
      instance.fitBounds(data.bounds, { padding: { top: 24, bottom: 180, left: 24, right: 24 }, duration: 0 });
      displayedBounds.current = boundsKey;
    }
  }, [data.bounds, grid, ready, theme]);
  const maximum = Math.max(1, ...grid.cells.map(cell => cell.count));
  return <section className={`map-stage ${styles.stage}`} aria-label="Trusted coordinate aggregates">
    <div ref={host} className={`map-canvas ${fallback ? styles.hidden : ""}`} aria-label="Interactive rounded crash coordinate grid" />
    {fallback && <svg className={styles.fallback} viewBox={`0 0 ${size.width} ${size.height}`} aria-label="Rounded crash coordinate grid, WebGL unavailable" role="img">
      {boundary.features.map((feature, index) => <path key={index} d={mapSvgPath(feature.geometry, data.bounds, size.width, size.height, "state", insets)} fill="var(--map-land)" stroke="var(--map-line)" strokeWidth="0.7" />)}
      {grid.cells.map(cell => {
        const [cx, cy] = projectMapPoint([cell.longitude, cell.latitude], data.bounds, size.width, size.height, "state", insets);
        const label = cellLabel(cell.longitude, cell.latitude, cell.count);
        return <circle key={`${cell.longitude}:${cell.latitude}`} cx={cx} cy={cy} r={3 + 15 * Math.sqrt(cell.count / maximum)} className={styles.cell} aria-label={label} onMouseEnter={() => setReadout(label)} onMouseLeave={() => setReadout("")}><title>{label}</title></circle>;
      })}
    </svg>}
    {readout && <p className={styles.readout} role="status">{readout}</p>}
    <div className={styles.footer}>
      <div className={styles.heading}><strong>Recorded crashes · {grid.precisionDegrees}° coordinate cells</strong><div className={styles.controls} role="group" aria-label="Coordinate map controls"><button aria-label="Zoom in" disabled={fallback} onClick={() => map.current?.zoomIn()}><Plus size={16} /></button><button aria-label="Zoom out" disabled={fallback} onClick={() => map.current?.zoomOut()}><Minus size={16} /></button><button aria-label="Reset coordinate map" disabled={fallback} onClick={() => map.current?.fitBounds(data.bounds, { padding: { top: 24, bottom: 180, left: 24, right: 24 }, duration: 0 })}><RotateCcw size={16} /></button></div></div>
      <p>Cell centres are rounded locations, not exact crash sites or assigned areas. Size indicates crash count.</p>
      {fallback && <p>Static map. Interactive rendering is unavailable.</p>}
      <p>{grid.locatedCrashCount !== undefined && grid.unlocatedCrashCount !== undefined ? `${number(grid.locatedCrashCount)} crashes with trusted coordinates · ${number(grid.unlocatedCrashCount)} without.` : "Complete location coverage is unavailable; counts describe returned cells only."}</p>
      <p className={grid.truncated ? styles.warning : undefined}>{grid.totalCells !== undefined ? `Showing ${number(grid.returnedCells)} of ${number(grid.totalCells)} cells.${grid.truncated ? " Other cells are not shown." : ""}` : `Showing ${number(grid.returnedCells)} returned cells; the total number of cells is unavailable.`}</p>
      <details onToggle={event => setValuesOpen(event.currentTarget.open)}><summary>View coordinate-cell values</summary>{valuesOpen && <div className={styles.table} tabIndex={0} aria-label="Coordinate cell values"><table><caption>Crash counts in returned {grid.precisionDegrees}° cells. No counts for other metrics or areas are inferred.</caption><thead><tr><th>Longitude</th><th>Latitude</th><th>Crashes</th></tr></thead><tbody>{grid.cells.map(cell => <tr key={`${cell.longitude}:${cell.latitude}`}><td>{cell.longitude.toFixed(1)}°</td><td>{cell.latitude.toFixed(1)}°</td><td>{number(cell.count)}</td></tr>)}</tbody></table></div>}</details>
    </div>
  </section>;
}
