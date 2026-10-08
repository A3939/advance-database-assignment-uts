/** Deterministic, script-free SVG used by Studio previews and print exports.
 * Inputs are validated saved host results, never user-supplied SVG or JavaScript. */
import type { AnalysisRow } from "./analysis-contracts";
export const escapeXml = (value: unknown): string => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]!);
export interface StudioFigure {
  title: string; kind: "line" | "bar" | "table" | "kpi" | "map";
  rows: AnalysisRow[]; x: string; y: string; series: string | null; unit: string;
  map?: { geojson?: unknown; counts?: { id: string; name: string; value: number | null }[];
    cells?: { longitude: number; latitude: number; count: number }[]; precisionDegrees?: number };
}
const palette = ["#16697a", "#a84d3a", "#7356a0", "#927026", "#237d55", "#475569"];
const n = (value: number) => Number(value.toFixed(2));
const num = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const label = (value: unknown, limit = 50) => { const text = String(value ?? "Unknown"); return text.length > limit ? `${text.slice(0, limit - 1)}…` : text; };
const text = (x: number, y: number, value: unknown, extra = "") => `<text x="${n(x)}" y="${n(y)}" ${extra}>${escapeXml(value)}</text>`;
function svg(title: string, height: number, contents: string) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 ${height}" role="img" aria-label="${escapeXml(title)}"><title>${escapeXml(title)}</title><rect width="800" height="${height}" fill="white"/><g font-family="Arial, PingFang SC, Heiti SC, sans-serif" font-size="12" fill="#243444">${contents}</g></svg>`;
}
export function renderStudioFigure(figure: StudioFigure): string {
  if (figure.rows.length > 10000 || JSON.stringify(figure).length > 12000000) throw Error("The selected figure exceeds the bounded renderer capacity.");
  if (figure.kind === "map") return renderMap(figure);
  if (figure.kind === "table" || figure.kind === "kpi") {
    const columns = [...new Set(figure.rows.flatMap(row => Object.keys(row)))];
    if (columns.length > 16 || figure.rows.length > 500) throw Error("Use the report table preview for this large table.");
    const width = 744 / Math.max(1, columns.length), height = 82 + figure.rows.length * 26;
    let content = text(28, 25, figure.title, 'font-weight="700" font-size="17"');
    columns.forEach((key, i) => { content += text(28 + width * i, 53, label(key, 22), 'font-weight="700"'); });
    figure.rows.forEach((row, i) => { content += `<path d="M28 ${62 + i * 26}H772" stroke="#dde4e8"/>`; columns.forEach((key, j) => { content += text(28 + width * j, 80 + i * 26, label(row[key], Math.max(8, Math.floor(width / 7)))); }); });
    return svg(figure.title, height, content);
  }
  if (!figure.rows.length) return svg(figure.title, 150, text(28, 35, figure.title) + text(28, 82, "No observations. No zero values substituted."));
  const values = figure.rows.map(row => row[figure.y]).filter(num);
  if (!values.length) return svg(figure.title, 150, text(28, 35, figure.title) + text(28, 82, "Values are unknown or unavailable."));
  const min = Math.min(0, ...values), max = Math.max(0, ...values), span = max - min || 1;
  if (figure.kind === "bar") {
    if (figure.rows.length > 100) throw Error("This bar chart exceeds the supported label capacity. Use a table.");
    const height = Math.max(210, 110 + figure.rows.length * 26), left = 260, right = 715;
    const scale = (value: number) => left + (value - min) / span * (right - left);
    let content = text(28, 28, figure.title, 'font-size="17" font-weight="700"') + text(28, 49, figure.unit);
    const groups = [...new Set(figure.rows.map(row => figure.series ? String(row[figure.series] ?? "Unknown") : ""))];
    figure.rows.forEach((row, i) => {
      const y = 78 + i * 26, value = row[figure.y], group = figure.series ? String(row[figure.series] ?? "Unknown") : "";
      content += text(28, y + 12, label(`${group ? `${group} · ` : ""}${row[figure.x] ?? "Unknown"}`, 36));
      if (num(value)) {
        const zero = scale(0), at = scale(value);
        content += `<rect x="${n(Math.min(zero, at))}" y="${y}" width="${n(Math.max(0, Math.abs(at - zero)))}" height="17" fill="${palette[groups.indexOf(group) % palette.length]}"/>`;
        content += text(725, y + 12, value.toLocaleString("en-AU", { maximumFractionDigits: 2 }));
      } else content += text(left, y + 12, "Unknown", 'fill="#64748b"');
    });
    content += `<path d="M${n(scale(0))} 68V${height - 26}" stroke="#85939f"/>`;
    return svg(figure.title, height, content);
  }
  const width = 654, left = 84, top = 75, bottom = 327;
  const numericX = figure.rows.every(row => num(row[figure.x]));
  const categories = [...new Set(figure.rows.map(row => String(row[figure.x] ?? "Unknown")))];
  if (numericX) categories.sort((a,b) => Number(a) - Number(b));
  const xMin = numericX ? Number(categories[0]) : 0, xSpan = numericX ? Number(categories.at(-1)) - xMin : 1;
  const series = [...new Set(figure.rows.map(row => figure.series ? String(row[figure.series] ?? "Unknown") : "Selected source"))];
  const height = Math.max(424, 405 + Math.ceil(series.length / 3) * 18);
  const sx = (category: string) => left + (categories.length === 1 ? width / 2 : numericX ? (Number(category) - xMin) / (xSpan || 1) * width : categories.indexOf(category) / (categories.length - 1) * width);
  const sy = (value: number) => bottom - (value - min) / span * (bottom - top);
  let content = text(28, 28, figure.title, 'font-size="17" font-weight="700"') + text(28, 50, figure.unit);
  for (let i = 0; i <= 4; i++) { const value = min + span * i / 4, y = sy(value); content += `<path d="M${left} ${n(y)}H${left + width}" stroke="#dce3e8"/>` + text(left - 9, y + 4, value.toLocaleString("en-AU", { maximumFractionDigits: 1 }), 'text-anchor="end"'); }
  const tickIndexes = new Set(Array.from({length: Math.min(8,categories.length)},(_,i)=>Math.round(i*(categories.length-1)/Math.max(1,Math.min(8,categories.length)-1))));
  if (numericX) for(let i=0;i<=4;i++){const value=xMin+xSpan*i/4;content+=text(sx(String(value)),348,n(value),'text-anchor="middle"');}
  else categories.forEach((category, i) => { if (tickIndexes.has(i)) content += text(sx(category), 348, label(category, 16), 'text-anchor="middle"'); });
  series.forEach((key, index) => {
    const color = palette[index % palette.length]; let path = "", penDown = false;
    const rows = figure.rows.filter(row => (figure.series ? String(row[figure.series] ?? "Unknown") : "Selected source") === key);
    const known = new Map(rows.map(row => [String(row[figure.x] ?? "Unknown"), row[figure.y]]));
    if (known.size !== rows.length) throw Error("Chart categories repeat within a series; no implicit aggregation is permitted.");
    // Numeric series may have different observed x positions. Missing categories
    // in other series are not gaps; explicit unknown y values still break a line.
    const observedCategories = numericX ? categories.filter(category => known.has(category)) : categories;
    for (const category of observedCategories) { const value = known.get(category); if (!num(value)) { penDown = false; continue; } const x = sx(category), y = sy(value); path += `${penDown ? "L" : "M"}${n(x)} ${n(y)} `; penDown = true; content += `<circle data-x="${escapeXml(category)}" data-series="${escapeXml(key)}" cx="${n(x)}" cy="${n(y)}" r="2.6" fill="${color}"/>`; }
    content += `<path d="${path}" fill="none" stroke="${color}" stroke-width="2.2"/>`;
    const x = 28 + (index % 3) * 246, y = 379 + Math.floor(index / 3) * 18;
    content += `<path d="M${x} ${y - 4}h16" stroke="${color}" stroke-width="3"/>` + text(x + 23, y, label(key, 30));
  });
  content += text(28, height - 8, "Gaps remain unknown; sources are not pooled.", 'font-size="10" fill="#64748b"');
  return svg(figure.title, height, content);
}
function renderMap(figure: StudioFigure): string {
  const map = figure.map; if (!map) throw Error("A saved map requires its verified geometry or coordinate grid.");
  type Point = [number, number]; type Shape = { id: string; name: string; rings: Point[][]; value: number | null };
  const shapes: Shape[] = [], points: Point[] = [];
  const cellRows = map.cells ?? [];
  if (map.geojson) {
    const collection = map.geojson as { type?: string; features?: { id?: string; properties?: Record<string, unknown>; geometry?: { type: string; coordinates: unknown } }[] };
    if (collection.type !== "FeatureCollection" || !Array.isArray(collection.features) || collection.features.length > 10000) throw Error("Unsupported saved boundary geometry.");
    for (const feature of collection.features) {
      const properties = feature.properties ?? {}, geometry = feature.geometry;
      const id = String(properties.lga_code_2024 ?? feature.id ?? ""), name = String(properties.lga_name_2024 ?? properties.state_name_2021 ?? "");
      if (!geometry || !["Polygon", "MultiPolygon"].includes(geometry.type)) throw Error("Map polygons are required.");
      const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
      if (!Array.isArray(polygons)) throw Error("Invalid saved map geometry.");
      const rings: Point[][] = [];
      for (const polygon of polygons) {
        if (!Array.isArray(polygon)) throw Error("Invalid saved polygon.");
        for (const ring of polygon) {
          if (!Array.isArray(ring) || ring.length < 4) throw Error("Invalid saved polygon ring.");
          const valid = ring.map(raw => { if (!Array.isArray(raw) || !num(raw[0]) || !num(raw[1]) || Math.abs(raw[0]) > 180 || Math.abs(raw[1]) > 90) throw Error("Invalid geographic coordinate."); return [raw[0], raw[1]] as Point; });
          rings.push(valid); for (const point of valid) points.push(point);
          if (points.length > 500000) throw Error("Boundary exceeds supported print capacity.");
        }
      }
      const count = map.counts?.find(row => row.id === id || row.name === name);
      shapes.push({ id, name, rings, value: count?.value ?? null });
    }
  } else if (cellRows.length) {
    if (cellRows.length > 10000) throw Error("Coordinate grid exceeds supported print capacity.");
    cellRows.forEach(cell => { if (![cell.longitude, cell.latitude, cell.count].every(num) || Math.abs(cell.longitude) > 180 || Math.abs(cell.latitude) > 90 || cell.count < 0) throw Error("Invalid saved coordinate grid."); points.push([cell.longitude, cell.latitude]); });
  }
  if (!points.length) throw Error("This spatial result has no verified printable geometry.");
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const xmin = xs.reduce((a,b)=>Math.min(a,b)), xmax = xs.reduce((a,b)=>Math.max(a,b)), ymin = ys.reduce((a,b)=>Math.min(a,b)), ymax = ys.reduce((a,b)=>Math.max(a,b));
  const factor = Math.cos((ymin + ymax) / 2 * Math.PI / 180), ratio = Math.min(730 / Math.max(0.01, (xmax - xmin) * factor), 420 / Math.max(0.01, ymax - ymin));
  const xoff = 35 + (730 - (xmax - xmin) * factor * ratio) / 2, yoff = 75 + (420 - (ymax - ymin) * ratio) / 2;
  const project = (p: Point) => [xoff + (p[0] - xmin) * factor * ratio, yoff + (ymax - p[1]) * ratio];
  const values = (map.counts?.map(row=>row.value) ?? cellRows.map(cell=>cell.count)).filter(num), max = Math.max(1,...values);
  const color = (value: number | null) => value === null ? "#e4e8eb" : `hsl(193 58% ${92 - 56 * Math.sqrt(value / max)}%)`;
  let content = text(28, 28, figure.title, 'font-size="17" font-weight="700"') + text(28, 50, `${figure.unit} · North up · saved geometry`);
  for (const shape of shapes) { const path = shape.rings.map(ring => ring.map((p,i)=>`${i ? "L" : "M"}${project(p).map(n).join(" ")}`).join(" ")+"Z").join(" "); content += `<path d="${path}" fill="${color(shape.value)}" fill-rule="evenodd" stroke="#82939b" stroke-width="0.5"><title>${escapeXml(`${shape.name}: ${shape.value ?? "Unknown"}`)}</title></path>`; }
  for (const cell of cellRows) { const [x,y]=project([cell.longitude,cell.latitude]);const size=Math.max(2,(map.precisionDegrees??0.01)*ratio);content+=`<rect x="${n(x-size/2)}" y="${n(y-size/2)}" width="${n(size)}" height="${n(size)}" fill="${color(cell.count)}"><title>${escapeXml(`${cell.longitude}, ${cell.latitude}: ${cell.count}`)}</title></rect>`; }
  for(let i=0;i<5;i++){content+=`<rect x="${28+i*32}" y="526" width="32" height="10" fill="${color(max*i/4)}"/>`;}
  content+=text(28,551,"0")+text(188,551,max.toLocaleString("en-AU"),'text-anchor="end"')+`<rect x="226" y="526" width="16" height="10" fill="#e4e8eb"/>`+text(250,535,"Unknown / no admitted count")+text(28,575,"Count distribution, not exposure-adjusted risk. No external basemap or tiles.",'font-size="11"');
  return svg(figure.title,595,content);
}
