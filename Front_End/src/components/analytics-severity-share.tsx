"use client";

import { useId, useLayoutEffect, useRef, useState } from "react";
import { severityComposition, formatSeverityShare, type SeverityValue } from "@/services/severity-comparison";
import type { Source } from "@/services/contracts";
import styles from "./analytics.module.css";

export default function AnalyticsSeverityShare({rows, sources = []}: {rows: SeverityValue[]; sources?: Source[]}) {
  const composition = severityComposition(rows, sources);
  const tooltipId = useId();
  const host = useRef<HTMLDivElement>(null);
  const tooltip = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<{source: number; segment: number | null; x: number; y: number} | null>(null);
  const show = (source: number, segment: number | null, clientX: number, clientY: number) => {
    const bounds = host.current?.getBoundingClientRect();
    if (bounds) setActive({source, segment, x:clientX - bounds.left, y:clientY - bounds.top});
  };
  useLayoutEffect(() => {
    if (!active || !tooltip.current || !host.current) return;
    const tip = tooltip.current;
    const bounds = host.current.getBoundingClientRect();
    const left = Math.max(0, Math.min(active.x + 20, bounds.width - tip.offsetWidth));
    const preferredTop = active.y + 20 + tip.offsetHeight <= bounds.height
      ? active.y + 20 : active.y - tip.offsetHeight - 12;
    tip.style.left = `${left}px`;
    tip.style.top = `${Math.max(0, Math.min(preferredTop, bounds.height - tip.offsetHeight))}px`;
    tip.style.visibility = "visible";
  }, [active]);
  const current = active == null ? null : composition[active.source];
  return <div ref={host} className={styles.shareComposition} style={{position:"relative"}} aria-label="Severity shares within each source">
    <div className={styles.shareAxis} aria-hidden="true">{[0,25,50,75,100].map(value => <span key={value} style={{left:`${value}%`}}>{value}%</span>)}</div>
    {composition.map(({source, segments, available, unclassifiedShare}, sourceIndex) => {
      const fatal = segments.find(row => row.tone === 0);
      const hovered = active?.source === sourceIndex;
      return <section className={styles.shareSource} key={source ?? "selected"} data-muted={active !== null && !hovered} aria-label={`${source ?? "Selected source"} severity composition`}>
        <div className={styles.shareSourceLabel}><strong>{source ?? "Selected"}</strong>{fatal && <span className={styles.shareFatal}>Fatal {formatSeverityShare(fatal.share)}</span>}</div>
        <div className={styles.shareSourceChart} onPointerLeave={() => setActive(null)}>
          {available ? <div className={styles.shareTrack} role="img" tabIndex={0}
            data-active={hovered}
            aria-label={segments.map(row => `${row.label}: ${formatSeverityShare(row.share)}`).join("; ")}
            aria-describedby={hovered ? tooltipId : undefined}
            onPointerMove={event => {
              const segment = (event.target as HTMLElement).closest<HTMLElement>("[data-segment]")?.dataset.segment;
              show(sourceIndex, segment == null ? null : Number(segment), event.clientX, event.clientY);
            }}
            onFocus={event => {
              const bounds = event.currentTarget.getBoundingClientRect();
              show(sourceIndex, null, bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);
            }}
            onBlur={() => setActive(null)}
            onKeyDown={event => {if (event.key === "Escape") setActive(null);}}>
            {segments.map((row, segmentIndex) => row.share !== null && <span key={row.label} className={styles.shareSegment} data-tone={row.tone}
              data-segment={segmentIndex}
              data-muted={hovered && active?.segment !== null && active?.segment !== segmentIndex}
              style={{width:`${row.share}%`}} aria-label={`${row.label}: ${formatSeverityShare(row.share)}`}>
              {row.share! >= 8 && <b>{formatSeverityShare(row.share)}</b>}
            </span>)}
            {unclassifiedShare != null && unclassifiedShare > .000001 && <span className={styles.shareSegment} data-tone="5"
              data-segment={segments.length}
              data-muted={hovered && active?.segment !== null && active?.segment !== segments.length}
              style={{width:`${unclassifiedShare}%`}} aria-label={`Unclassified / unavailable: ${formatSeverityShare(unclassifiedShare)}`}/>}
          </div> : <p className={styles.shareUnavailable}>Share unavailable for this selection.</p>}
          <ul className={styles.shareNativeLegend} aria-label={`${source ?? "Selected source"} original categories`}>{segments.map(row => <li key={row.label}><i data-tone={row.tone} aria-hidden="true"/><span>{row.label} <strong>{formatSeverityShare(row.share)}</strong></span></li>)}{available && unclassifiedShare != null && unclassifiedShare > .000001 && <li><i data-tone="5" aria-hidden="true"/><span>Unclassified / unavailable <strong>{formatSeverityShare(unclassifiedShare)}</strong></span></li>}</ul>
        </div>
      </section>;
    })}
    {current?.available && <div ref={tooltip} id={tooltipId} role="tooltip" style={{
      position:"absolute", left:0, top:0, visibility:"hidden", zIndex:10, pointerEvents:"none",
      width:"max-content", maxWidth:"min(310px, 100%)", boxSizing:"border-box", padding:12,
      border:"1px solid var(--border)", borderRadius:4, background:"var(--surface-elevated)",
      color:"var(--text-primary)", fontFamily:"Inter, system-ui, sans-serif", fontSize:12,
      fontWeight:400, lineHeight:"22px", whiteSpace:"pre-wrap", boxShadow:"0 4px 14px #0002",
    }}>{[
      current.source ?? "Selected source",
      ...current.segments.map(row => `${row.label}: ${formatSeverityShare(row.share)}`),
      ...(current.unclassifiedShare != null && current.unclassifiedShare > .000001
        ? [`Unclassified / unavailable: ${formatSeverityShare(current.unclassifiedShare)}`] : []),
    ].join("\n")}</div>}
  </div>;
}
