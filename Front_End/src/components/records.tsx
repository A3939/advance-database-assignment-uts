"use client";
import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  Search,
  Table2,
  ArrowUpDown,
  ArrowUpRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useWorkspace } from "./workspace";
import { arsia } from "@/services";
import type { Records, Sort } from "@/services/contracts";
export function CrashRecords({
  aggregateCount,
}: {
  aggregateCount: number | null;
}) {
  const { filters, showEvidence } = useWorkspace();
  const [open, setOpen] = useState(false),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(1),
    [sort, setSort] = useState<Sort>({ field: "date", direction: "desc" }),
    [records, setRecords] = useState<Records | null>(null);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    arsia
      .getCrashRecords(filters, { page, pageSize: 8, search }, sort)
      .then((r) => {
        if (alive) setRecords(r.data);
      });
    return () => {
      alive = false;
    };
  }, [filters, page, search, sort, open]);
  const totalPages = Math.max(1, Math.ceil((records?.total || 0) / 8));
  const changeSort = (field: Sort["field"]) => {
    setPage(1);
    setSort({
      field,
      direction:
        sort.field === field && sort.direction === "asc" ? "desc" : "asc",
    });
  };
  return (
    <section className={`panel records-panel ${open ? "expanded" : ""}`}>
      <button
        className="records-toggle"
        aria-expanded={open}
        aria-controls="records-body"
        onClick={() => setOpen(!open)}
      >
        <span className="records-title">
          <ChevronDown size={19} className={open ? "turned" : ""} />
          <Database size={21} />
          <strong>Crash records</strong>
          <span className="muted">
            {aggregateCount === null
              ? "No aggregate"
              : `${aggregateCount.toLocaleString("en-AU")} aggregate crashes`}
          </span>
        </span>
        <span className="records-hint">
          Illustrative sample{" "}
          <span className="fake-control">
            <Table2 size={17} />
            {open ? "Hide table" : "Show table"}
          </span>
        </span>
      </button>
      {open && (
        <div id="records-body" className="records-body">
          <div className="table-toolbar">
            <div>
              <h3>Explore the illustrative records</h3>
              <p>
                Independent sample rows. These do not substantiate the aggregate
                KPIs.
              </p>
            </div>
            <label className="search-box">
              <Search size={16} />
              <input
                aria-label="Search crash records"
                placeholder="Search ID, region, severity…"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </label>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {(["id", "date", "region", "severity"] as const).map(
                    (field) => (
                      <th
                        key={field}
                        aria-sort={
                          sort.field === field
                            ? sort.direction === "asc"
                              ? "ascending"
                              : "descending"
                            : "none"
                        }
                      >
                        <button onClick={() => changeSort(field)}>
                          {field === "id"
                            ? "Record ID"
                            : field[0].toUpperCase() + field.slice(1)}
                          <ArrowUpDown size={13} />
                        </button>
                      </th>
                    ),
                  )}
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {records?.rows.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.id}</td>
                    <td>{r.date}</td>
                    <td>{r.region}</td>
                    <td>
                      <span
                        className={`severity-tag ${r.severity.toLowerCase().includes("fatal") ? "fatal" : ""}`}
                      >
                        {r.severity}
                      </span>
                    </td>
                    <td>
                      <button
                        className="table-evidence"
                        aria-label={`View ${r.id} evidence`}
                        onClick={() =>
                          showEvidence({
                            title: r.id,
                            description:
                              "Fictional record for frontend interaction testing. This row is not a real accident and is not linked to official Raw data.",
                            rows: Object.entries(r).map(([label, value]) => ({
                              label,
                              value: String(value),
                            })),
                          })
                        }
                      >
                        <ArrowUpRight size={17} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {records?.rows.length === 0 && (
              <div className="empty-inline">
                No illustrative records match this selection.
              </div>
            )}
          </div>
          <div className="pagination">
            <span>
              {records?.total || 0} illustrative records · page {page} of{" "}
              {totalPages}
            </span>
            <div>
              <Button
                variant="outline"
                size="sm"
                aria-label="Previous records page"
                disabled={page === 1}
                onClick={() => setPage(page - 1)}
              >
                <ChevronLeft size={16} />
              </Button>
              <Button
                variant="outline"
                size="sm"
                aria-label="Next records page"
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
              >
                <ChevronRight size={16} />
              </Button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
