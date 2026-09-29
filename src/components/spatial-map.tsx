"use client";
import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import { Info, Maximize, Minus, Plus, RotateCcw } from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import type { MapData, Source } from "@/services/contracts";
import { mapPadding, mapSvgPath, projectMapPoint } from "@/lib/map-viewport";
interface Props {
  data: MapData;
  onSelect: (id: string, name?: string) => void;
  onSourceSelect: (source: Source) => void;
  onShowEvidence: () => void;
}

// One concentration scale for both map levels. Missing observations stay neutral.
function concentrationToken(count: number | undefined, maximum: number) {
  if (count === undefined) return "--map-land";
  return `--map-ramp-${Math.max(1, Math.min(7, Math.ceil((count / Math.max(1, maximum)) * 7)))}`;
}
function regionLabel(current: MapData, id: string, name: string) {
  const region = current.regions.find(r => r.id === id);
  return current.regionMode === "lga"
    ? `${name} LGA · ${region ? `${region.count.toLocaleString("en-AU")} crashes · ${region.fatalCrashes === null ? "Unknown" : region.fatalCrashes?.toLocaleString("en-AU")} fatal` : "No data for this period"}`
    : `${name}${current.illustrationOnly ? "" : " · boundary only"}`;
}
function duration(ms: number) {
  return matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : ms;
}
export default function SpatialMap({
  data,
  onSelect,
  onSourceSelect,
  onShowEvidence,
}: Props) {
  const { theme } = useTheme();
  const host = useRef<HTMLDivElement>(null),
    map = useRef<maplibregl.Map | null>(null),
    markers = useRef<maplibregl.Marker[]>([]),
    view = useRef("");
  const context = useRef({ data, onSelect, onSourceSelect });
  useEffect(() => {
    context.current = { data, onSelect, onSourceSelect };
  }, [data, onSelect, onSourceSelect]);
  const [loaded, setLoaded] = useState(false),
    [fallback, setFallback] = useState(false),
    [boundary, setBoundary] = useState<{
      url: string;
      geo: FeatureCollection;
    } | null>(null),
    [active, setActive] = useState(""),
    [hover, setHover] = useState<{ id: string; name: string; url: string } | null>(null),
    [mapError, setMapError] = useState("");
  const [fallbackSize, setFallbackSize] = useState({ width: 800, height: 600 });
  function fitPadding(current = context.current.data) {
    return mapPadding(
      current.bounds,
      host.current?.clientWidth || 800,
      host.current?.clientHeight || 600,
      current.level,
    );
  }
  useEffect(() => {
    if (!fallback || !host.current) return;
    const element = host.current;
    const observer = new ResizeObserver(() =>
      setFallbackSize({
        width: element.clientWidth,
        height: element.clientHeight,
      }),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [fallback]);

  useEffect(() => {
    let alive = true;
    fetch(data.boundaryUrl)
      .then((r) => {
        if (!r.ok) throw Error("Boundary file unavailable");
        return r.json();
      })
      .then((geo: FeatureCollection) => {
        if (!alive) return;
        // The two ABS datasets have distinct schemas; normalise only the map view properties.
        geo.features = geo.features.map((f) => ({
          ...f,
          properties: {
            ...f.properties,
            region_id:
              f.properties?.state_code_2021 ?? f.properties?.lga_code_2024,
            region_name:
              f.properties?.state_name_2021 ?? f.properties?.lga_name_2024,
          },
        }));
        // LGA files also carry state_name_2021: prefer the finer label in that case.
        for (const f of geo.features)
          if (f.properties?.lga_name_2024)
            f.properties.region_name = f.properties.lga_name_2024;
        setBoundary({ url: data.boundaryUrl, geo });
        setActive("");
        setHover(null);
        setMapError("");
      })
      .catch(() => {
        if (alive) setMapError("The local boundary file could not be loaded.");
      });
    return () => {
      alive = false;
    };
  }, [data.boundaryUrl]);
  function choose(id: string, name: string) {
    const {
      data: current,
      onSelect: select,
      onSourceSelect: enter,
    } = context.current;
    if (current.level === "country") {
      const state = current.states?.find((s) => s.code === id);
      if (state?.available && state.source) enter(state.source);
      else setActive(`${name} · No data for this period`);
    } else {
      const label = regionLabel(current, id, name);
      setActive(current.regionMode === "lga" ? "" : label);
      select(id, name);
      map.current?.setFilter("selection", ["==", ["get", "region_id"], id]);
    }
  }
  const chooseRef = useRef(choose);
  useEffect(() => {
    chooseRef.current = choose;
  });
  useEffect(() => {
    if (!host.current) return;
    const style = getComputedStyle(host.current),
      token = (n: string) => style.getPropertyValue(n).trim();
    maplibregl.setWorkerUrl("/vendor/maplibre/maplibre-gl-worker.mjs");
    let instance: maplibregl.Map;
    try {
      instance = new maplibregl.Map({
        container: host.current,
        style: {
          version: 8,
          sources: {},
          layers: [
            {
              id: "background",
              type: "background",
              paint: { "background-color": token("--map-background") },
            },
          ],
        },
        attributionControl: false,
        renderWorldCopies: false,
        minZoom: 1,
        maxZoom: 12,
        canvasContextAttributes: { antialias: true },
        dragRotate: false,
        pitchWithRotate: false,
      });
    } catch {
      queueMicrotask(() => setFallback(true));
      return;
    }
    map.current = instance;
    instance.on("error", () =>
      setMapError(
        "The map could not render. Local boundaries are available in the evidence panel.",
      ),
    );
    instance.on("load", () => {
      instance.addSource("boundaries", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
        promoteId: "region_id",
      });
      instance.addLayer({
        id: "regions",
        type: "fill",
        source: "boundaries",
        paint: {
          "fill-color": token("--map-land"),
          "fill-opacity": 0.9,
          "fill-color-transition": { duration: 200 },
        },
      });
      instance.addLayer({
        id: "edges",
        type: "line",
        source: "boundaries",
        paint: {
          "line-color": token("--map-line"),
          "line-width": 0.8,
          "line-opacity": 0.7,
        },
      });
      instance.addLayer({
        id: "hover-edge",
        type: "line",
        source: "boundaries",
        paint: {
          "line-color": token("--map-highlight"),
          "line-width": 2,
          "line-opacity": [
            "case",
            ["boolean", ["feature-state", "hover"], false],
            1,
            0,
          ],
        },
      });
      instance.addLayer({
        id: "selection",
        type: "line",
        source: "boundaries",
        filter: ["==", ["get", "region_id"], ""],
        paint: { "line-color": token("--map-highlight"), "line-width": 2 },
      });
      let hovered: string | number | undefined;
      instance.on("mousemove", "regions", (e) => {
        if (hovered !== undefined)
          instance.setFeatureState(
            { source: "boundaries", id: hovered },
            { hover: false },
          );
        const f = e.features?.[0];
        if (!f) return;
        hovered = f.id;
        if (hovered !== undefined)
          instance.setFeatureState(
            { source: "boundaries", id: hovered },
            { hover: true },
          );
        const current = context.current.data,
          state = current.states?.find(
            (s) => s.code === f.properties.region_id,
          );
        setHover({ id: f.properties.region_id, name: f.properties.region_name, url: current.boundaryUrl });
        instance.getCanvas().style.cursor =
          current.level === "country" && !state?.available
            ? "default"
            : "pointer";
      });
      instance.on("mouseleave", "regions", () => {
        if (hovered !== undefined)
          instance.setFeatureState(
            { source: "boundaries", id: hovered },
            { hover: false },
          );
        setHover(null);
        instance.getCanvas().style.cursor = "";
      });
      instance.on("click", "regions", (e) => {
        const f = e.features?.[0];
        if (f)
          chooseRef.current(f.properties.region_id, f.properties.region_name);
      });
      setLoaded(true);
    });
    let refitPending = false;
    const refit = () => {
      refitPending = false;
      instance.fitBounds(context.current.data.bounds, {
        padding: fitPadding(),
        duration: 0,
      });
    };
    // Finish a drilldown before applying a resize/fullscreen refit.
    instance.on("moveend", () => {
      if (refitPending) refit();
    });
    const resize = new ResizeObserver(() => {
      instance.resize();
      if (!view.current) return;
      if (instance.isMoving()) refitPending = true;
      else refit();
    });
    resize.observe(host.current);
    return () => {
      resize.disconnect();
      markers.current.forEach((m) => m.remove());
      instance.remove();
      map.current = null;
    };
  }, []);
  useEffect(() => {
    const instance = map.current;
    if (!instance || !loaded || !boundary || boundary.url !== data.boundaryUrl)
      return;
    const changed = view.current !== data.boundaryUrl,
      first = !view.current;
    if (changed) {
      instance.resize();
      (instance.getSource("boundaries") as GeoJSONSource).setData(boundary.geo);
      instance.removeFeatureState({ source: "boundaries" });
      instance.setFilter("selection", ["==", ["get", "region_id"], ""]);
      instance.fitBounds(data.bounds, {
        padding: fitPadding(data),
        duration: first ? 0 : duration(700),
        essential: false,
      });
      view.current = data.boundaryUrl;
    }
    const style = getComputedStyle(host.current!),
      token = (n: string) => style.getPropertyValue(n).trim();
    const country = data.level === "country";
    const observations = country
      ? (data.states || []).map((s) => ({ id: s.code, count: s.count }))
      : data.regions;
    const maximum = Math.max(1, ...observations.map((r) => r.count ?? 0));
    const colors = observations.flatMap((r) => [
      r.id,
      token(concentrationToken(r.count, maximum)),
    ]);
    instance.setPaintProperty(
      "regions",
      "fill-color",
      colors.length
        ? [
            "match",
            ["get", "region_id"],
            colors[0],
            colors[1],
            ...colors.slice(2),
            token("--map-land"),
          ]
        : token("--map-land"),
    );
    instance.setPaintProperty(
      "background",
      "background-color",
      token("--map-background"),
    );
    instance.setPaintProperty("edges", "line-color", token("--map-line"));
    for (const layer of ["hover-edge", "selection"])
      instance.setPaintProperty(layer, "line-color", token("--map-highlight"));
    instance.setFilter("selection", ["==", ["get", "region_id"], data.selectedRegionId || ""]);
    markers.current.forEach((m) => m.remove());
    markers.current = [];
    if (country) {
      for (const state of data.states || []) {
        if (state.code === "9") continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "map-state-button";
        button.dataset.stateCode = state.code;
        button.textContent = state.label;
        button.setAttribute(
          "aria-label",
          state.available
            ? `Explore ${state.label}`
            : `${state.label}: no data for this period`,
        );
        button.onclick = () => chooseRef.current(state.code, state.name);
        markers.current.push(
          new maplibregl.Marker({ element: button })
            .setLngLat(state.coordinates)
            .addTo(instance),
        );
      }
    } else if (data.illustrationOnly)
      for (const [i, r] of data.regions.entries()) {
        if (!r.coordinates) continue;
        const hotspot = document.createElement("div");
        hotspot.className = `map-hotspot marker-${i}`;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "map-marker";
        button.setAttribute("aria-label", `Select ${r.name} demo hotspot`);
        const dot = document.createElement("span");
        dot.className = "marker-dot";
        const label = document.createElement("span");
        label.className = "marker-label";
        label.textContent = r.name;
        button.append(label);
        hotspot.append(dot, button);
        hotspot.onclick = () =>
          chooseRef.current(
            r.id,
            `${r.name}: ${r.count.toLocaleString("en-AU")} illustrative crashes`,
          );
        markers.current.push(
          new maplibregl.Marker({ element: hotspot, anchor: "center" })
            .setLngLat(r.coordinates)
            .addTo(instance),
        );
      }
    if (country || !data.illustrationOnly) return;
    // Keep the dots on their coordinates; only the clickable labels move apart.
    const placeLabels = () => {
      const width = host.current!.clientWidth,
        height = host.current!.clientHeight;
      const labels = markers.current
        .map((marker) => {
          const element = marker.getElement();
          const button =
            element.querySelector<HTMLButtonElement>(".map-marker")!;
          const point = instance.project(marker.getLngLat());
          return { element, button, point, top: point.y - 18 };
        })
        .sort((a, b) => a.point.y - b.point.y);
      for (let i = 1; i < labels.length; i++)
        labels[i].top = Math.max(labels[i].top, labels[i - 1].top + 42);
      const overflow = Math.max(
        0,
        (labels.at(-1)?.top ?? 0) + 36 - (height - 64),
      );
      for (const label of labels) {
        label.element.style.setProperty(
          "--label-offset-y",
          `${label.top - overflow - label.point.y + 18}px`,
        );
        const labelWidth = label.button.getBoundingClientRect().width;
        label.element.style.setProperty(
          "--label-offset-x",
          `${label.point.x + 25 + labelWidth > width - 8 ? -labelWidth - 18 : 25}px`,
        );
      }
    };
    placeLabels();
    instance.on("move", placeLabels);
    return () => {
      instance.off("move", placeLabels);
    };
  }, [data, boundary, loaded, theme]);
  const country = data.level === "country";
  const hoveredState = hover ? data.states?.find(s => s.code === hover.id) : undefined;
  const hoverReadout = hover?.url === data.boundaryUrl
    ? country
      ? `${hover.name} · ${hoveredState?.count !== undefined ? `${hoveredState.count.toLocaleString("en-AU")} recorded crashes` : "No data for this period"}`
      : regionLabel(data, hover.id, hover.name)
    : "";
  const boundaryOnly = !country && !data.illustrationOnly && data.regionMode !== "lga";
  const observations = country
    ? (data.states || []).map((s) => ({ id: s.code, count: s.count }))
    : data.regions;
  const maximum = Math.max(1, ...observations.map((r) => r.count ?? 0));
  return (
    <div className={`map-stage ${country ? "country-map" : ""} ${data.regionMode === "lga" ? "lga-map" : ""}`}>
      <div
        ref={host}
        className="map-canvas"
        aria-label="Interactive crash data map"
      />
      {fallback && boundary?.url === data.boundaryUrl && (
        <svg
          className="map-fallback"
          viewBox={`0 0 ${fallbackSize.width} ${fallbackSize.height}`}
          role="img"
          aria-label="Local ABS boundaries, WebGL unavailable"
        >
          {boundary.geo.features.map((f) => {
            const id = f.properties?.region_id,
              name = f.properties?.region_name,
              available = data.states?.some(
                (s) => s.code === id && s.available,
              );
            return (
              <path
                key={id}
                d={mapSvgPath(
                  f.geometry,
                  data.bounds,
                  fallbackSize.width,
                  fallbackSize.height,
                  data.level,
                )}
                fill={`var(${concentrationToken(observations.find((r) => r.id === id)?.count, maximum)})`}
                stroke="var(--map-line)"
                strokeWidth={data.selectedRegionId === id ? "2.5" : "1"}
                aria-pressed={data.selectedRegionId === id}
                onMouseEnter={() => setHover({ id, name, url: data.boundaryUrl })}
                onMouseLeave={() => setHover(null)}
                tabIndex={0}
                role="button"
                aria-label={`Select ${name}${country && !available ? " (no data)" : boundaryOnly ? " boundary" : ""}`}
                onClick={() => choose(id, name)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    choose(id, name);
                  }
                }}
              >
                <title>
                  {name}
                  {country
                    ? available
                      ? data.illustrationOnly
                        ? " · Demo crashes"
                        : " · Recorded crashes"
                      : " · No data"
                    : boundaryOnly
                      ? " · Boundary only"
                      : ""}
                </title>
              </path>
            );
          })}
          {country &&
            data.states
              ?.filter((state) => state.code !== "9")
              .map((state) => {
                const [x, y] = projectMapPoint(
                  state.coordinates,
                  data.bounds,
                  fallbackSize.width,
                  fallbackSize.height,
                  data.level,
                );
                return (
                  <text
                    key={state.code}
                    x={x}
                    y={y}
                    className="map-fallback-label"
                    textAnchor="middle"
                    dominantBaseline="middle"
                    aria-hidden="true"
                  >
                    {state.label}
                  </text>
                );
              })}
        </svg>
      )}
      {!country && (
        <>
          <div className="state-word" aria-hidden="true">
            {data.boundaryUrl.split("/").at(-1)?.slice(0, 3).toUpperCase()}
          </div>
          <div className="ocean-label" aria-hidden="true">
            {data.boundaryUrl.includes("qld") ? "Coral Sea" : "Tasman Sea"}
          </div>
        </>
      )}
      {data.regionMode === "lga" && (
        <div className="map-region-picker">
          <label>
            <span className="sr-only">Local government area</span>
            <select aria-label="Local government area" value={data.selectedRegionId || ""}
              onChange={e => e.target.value ? choose(e.target.value, data.regions.find(r => r.id === e.target.value)!.name) : onSelect("")}>
              <option value="">All LGAs · {data.regions.length} areas</option>
              {data.selectedRegionId && !data.regions.length && <option value={data.selectedRegionId}>Selected LGA · no data</option>}
              {data.regions.map(r => <option key={r.id} value={r.id}>{r.name} · {r.count.toLocaleString("en-AU")}</option>)}
            </select>
          </label>
          {data.selectedRegionId && <button type="button" onClick={onShowEvidence}>Area details ↗</button>}
        </div>
      )}
      {(hoverReadout || active) && (
        <div className="map-readout" role="status">
          {hoverReadout || active}
        </div>
      )}
      {mapError && (
        <div className="map-readout" role="alert">
          {mapError}
        </div>
      )}
      {!country && data.illustrationOnly && !data.regions.length && (
        <div className="map-empty">No hotspots for this selection</div>
      )}
      <div
        className={`map-legend${boundaryOnly ? " boundary-only-legend" : ""}`}
      >
        <span>
          {data.legendLabel ||
            (data.illustrationOnly
              ? "Illustrative concentration"
              : boundaryOnly
                ? "Boundaries only"
                : "Recorded crashes by source")}
        </span>
        {data.coverage && <span className="region-coverage">{data.coverage.percentage === null ? "No data for this period" : `${data.coverage.percentage}% matched · ${data.coverage.unmatched.toLocaleString("en-AU")} unmatched`}</span>}
        {!boundaryOnly && (
          <>
            <div>
              {Array.from({ length: 7 }, (_, i) => (
                <i key={i} style={{ background: `var(--map-ramp-${i + 1})` }} />
              ))}
            </div>
            <span className="legend-ends">
              <span>Lower</span>
              <span>Higher</span>
            </span>
          </>
        )}
        {data.unavailableReason && (
          <p className="map-availability-note">{data.unavailableReason}</p>
        )}
        {country && !data.illustrationOnly && (
          <p className="map-availability-note">
            Source definitions differ. Counts are not comparable risk rates.
          </p>
        )}
      </div>
      <div className="map-controls">
        <button
          aria-label="Zoom in"
          onClick={() => map.current?.zoomIn({ duration: duration(180) })}
          disabled={fallback}
        >
          <Plus size={19} />
        </button>
        <button
          aria-label="Zoom out"
          onClick={() => map.current?.zoomOut({ duration: duration(180) })}
          disabled={fallback}
        >
          <Minus size={19} />
        </button>
        <button
          aria-label="Reset map view"
          onClick={() =>
            map.current?.fitBounds(data.bounds, {
              padding: fitPadding(),
              duration: duration(250),
            })
          }
          disabled={fallback}
        >
          <RotateCcw size={17} />
        </button>
        <button
          aria-label="Expand map"
          onClick={async () => {
            try {
              const element = host.current?.parentElement;
              if (document.fullscreenElement) await document.exitFullscreen();
              else if (element?.requestFullscreen)
                await element.requestFullscreen();
              else setMapError("Fullscreen is unavailable in this browser.");
            } catch {
              setMapError("Fullscreen is unavailable in this browser.");
            }
          }}
        >
          <Maximize size={17} />
        </button>
        <button aria-label="Map layer evidence" onClick={onShowEvidence}>
          <Info size={17} />
        </button>
      </div>
      {fallback && (
        <small className="fallback-note">
          WebGL unavailable · local boundary fallback
        </small>
      )}
    </div>
  );
}
