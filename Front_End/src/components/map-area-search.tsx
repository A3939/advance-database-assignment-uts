"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Check, Search, X } from "lucide-react";

export interface MapAreaOption {
  id: string;
  name: string;
  keywords?: string;
  unavailable?: boolean;
}

/** A local, source-scoped combobox; selecting an option uses the map's drilldown. */
export default function MapAreaSearch({ options, selectedId, onSelect, onClear }: {
  options: MapAreaOption[];
  selectedId?: string;
  onSelect: (option: MapAreaOption) => void;
  onClear: () => void;
}) {
  const listId = useId();
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [listHeight, setListHeight] = useState(280);
  const matches = options.filter(option =>
    `${option.name} ${option.keywords || ""}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const active = matches[activeIndex];

  useEffect(() => {
    if (!open) return;
    const updateHeight = () => {
      const box = root.current?.getBoundingClientRect();
      const viewportTop = window.visualViewport?.offsetTop || 0;
      if (box) setListHeight(Math.max(0, Math.min(280, box.top - viewportTop - 16)));
    };
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    updateHeight();
    document.addEventListener("pointerdown", dismiss);
    window.addEventListener("resize", updateHeight);
    window.addEventListener("scroll", updateHeight, true);
    window.visualViewport?.addEventListener("resize", updateHeight);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("resize", updateHeight);
      window.removeEventListener("scroll", updateHeight, true);
      window.visualViewport?.removeEventListener("resize", updateHeight);
    };
  }, [open]);

  useEffect(() => {
    if (open && activeIndex >= 0)
      document.getElementById(`${listId}-${activeIndex}`)?.scrollIntoView({ block: "nearest" });
  }, [open, activeIndex, listId]);

  function select(option: MapAreaOption) {
    if (option.unavailable) return;
    setOpen(false);
    setQuery("");
    setActiveIndex(-1);
    onSelect(option);
  }

  return (
    <div className="map-area-search" ref={root} onBlur={event => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
    }}>
      <Search size={15} aria-hidden="true" />
      <input ref={input} role="combobox" aria-label="Search areas" placeholder="Search areas"
        aria-autocomplete="list" aria-expanded={open} aria-controls={open ? listId : undefined}
        aria-activedescendant={open && active ? `${listId}-${activeIndex}` : undefined}
        autoComplete="off" spellCheck={false} value={query}
        onFocus={() => { setOpen(true); setActiveIndex(-1); }}
        onClick={() => setOpen(true)}
        onChange={event => { setQuery(event.target.value); setOpen(true); setActiveIndex(-1); }}
        onKeyDown={event => {
          if (event.key === "Escape") {
            event.preventDefault(); event.stopPropagation(); setOpen(false);
          } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault(); setOpen(true);
            const step = event.key === "ArrowDown" ? 1 : -1;
            let next = activeIndex < 0 && step < 0 ? 0 : activeIndex;
            for (let i = 0; i < matches.length; i++) {
              next = (next + step + matches.length) % matches.length;
              if (!matches[next].unavailable) { setActiveIndex(next); break; }
            }
          } else if (event.key === "Enter" && open && active) {
            event.preventDefault(); select(active);
          } else if (event.key === "Tab") setOpen(false);
        }}
      />
      {(query || selectedId) && <button type="button" className="map-search-clear"
        aria-label={selectedId ? "Clear selected area" : "Clear area search"}
        onClick={() => { input.current?.focus(); setQuery(""); setOpen(false); setActiveIndex(-1); if (selectedId) onClear(); }}>
        <X size={13} />
      </button>}
      {open && <div className="map-area-results" style={{ maxHeight: listHeight }}>
        <ul id={listId} role="listbox" aria-label="Areas">
          {matches.map((option, index) => <li key={option.id} id={`${listId}-${index}`}
            role="option" aria-selected={option.id === (selectedId || "")}
            aria-disabled={option.unavailable || undefined}
            data-active={index === activeIndex}
            onPointerDown={event => event.preventDefault()}
            onPointerMove={() => setActiveIndex(index)}
            onClick={() => select(option)}>
            <span>{option.name}{option.unavailable && <small>No data for this period</small>}</span>
            {option.id === (selectedId || "") && <Check size={14} aria-hidden="true" />}
          </li>)}
        </ul>
        {!matches.length && <p role="status">No matching areas. Try another name.</p>}
      </div>}
    </div>
  );
}
