"use client";

import { useRef, useState } from "react";
import { Archive, ArchiveRestore, BookOpen, MoreHorizontal, Pencil, Search, Trash2 } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import type { Study, StudySummary } from "@/services/studio-contracts";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "./ui/dialog";
import styles from "./studio-library.module.css";

export type StudyLibraryAction = { type: "rename"; title: string } | { type: "archive"; archived: boolean } | { type: "delete" };
export type StudyLibraryTarget = Pick<Study, "id" | "title" | "revision" | "archived">;

export function StudySearch({ studies, onSelect }: { studies: StudySummary[]; onSelect: (id: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const results = studies.filter(study => study.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <>
    <button className={styles.icon} aria-label="Search studies" title="Search studies" onClick={() => { setQuery(""); setOpen(true); }}><Search size={17}/></button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className={styles.searchDialog}>
        <DialogTitle>Search studies</DialogTitle>
        <DialogDescription className={styles.srOnly}>Find active and archived studies by name.</DialogDescription>
        <label className={styles.searchInput}><Search size={18}/><input aria-label="Search by study name" placeholder="Search studies…" value={query} onChange={event => setQuery(event.target.value)}/></label>
        <div className={styles.results}>
          {!results.length && <p className={styles.empty}>No studies found.</p>}
          {results.map(study => <button key={study.id} onClick={() => {setOpen(false);void onSelect(study.id);}}><BookOpen size={17}/><span>{study.title}</span>{study.archived && <small>Archived</small>}</button>)}
        </div>
      </DialogContent>
    </Dialog>
  </>;
}

export function StudyLibraryList({ studies, activeId, disabledId, onSelect, onInspect, onAction }: {
  studies: StudySummary[]; activeId?: string; disabledId?: string;
  onSelect: (id: string) => Promise<void>;
  onInspect: (id: string) => Promise<StudyLibraryTarget>;
  onAction: (study: StudyLibraryTarget, action: StudyLibraryAction) => Promise<void>;
}) {
  const [editor, setEditor] = useState<{ type: "rename" | "delete"; study: StudyLibraryTarget } | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [dialogError, setDialogError] = useState("");
  const locked = useRef(false);
  async function choose(study: StudySummary, type: "rename" | "archive" | "delete") {
    if (locked.current) return;
    locked.current = true;setBusy(study.id);setError("");setDialogError("");
    try {
      const target = await onInspect(study.id);
      if (type === "archive") await onAction(target, { type, archived: !target.archived });
      else {setTitle(target.title);setEditor({type,study:target});}
    } catch (cause) {setError((cause as Error).message);}
    finally {locked.current = false;setBusy("");}
  }
  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    if (!editor || locked.current) return;
    locked.current = true;setBusy(editor.study.id);setDialogError("");
    try {
      await onAction(editor.study, editor.type === "rename" ? {type:"rename",title:title.trim()} : {type:"delete"});
      setEditor(null);
    } catch (cause) {setDialogError((cause as Error).message);}
    finally {locked.current = false;setBusy("");}
  }
  return <>
    <div className={styles.list} aria-label="Study list">
      {!studies.length && <p className={styles.empty}>No studies here yet.</p>}
      {studies.map(study => <div className={styles.row} data-active={study.id === activeId} key={study.id}>
        <button className={styles.select} aria-current={study.id === activeId ? "page" : undefined} title={study.title} onClick={() => void onSelect(study.id)}><BookOpen size={15}/><span>{study.title}</span></button>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild><button className={styles.more} aria-label={`Options for ${study.title}`} disabled={!!busy || study.id === disabledId}><MoreHorizontal size={17}/></button></DropdownMenu.Trigger>
          <DropdownMenu.Portal><DropdownMenu.Content className={styles.menu} align="start" side="right" sideOffset={6} collisionPadding={12}>
            <DropdownMenu.Item onSelect={() => void choose(study, "rename")}><Pencil size={15}/>Rename</DropdownMenu.Item>
            <DropdownMenu.Item onSelect={() => void choose(study, "archive")}>{study.archived ? <ArchiveRestore size={15}/> : <Archive size={15}/>} {study.archived ? "Restore" : "Archive"}</DropdownMenu.Item>
            <DropdownMenu.Separator className={styles.separator}/>
            <DropdownMenu.Item className={styles.destructive} onSelect={() => void choose(study, "delete")}><Trash2 size={15}/>Delete</DropdownMenu.Item>
          </DropdownMenu.Content></DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>)}
    </div>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <Dialog open={!!editor} onOpenChange={open => {if(!open && !locked.current)setEditor(null);}}>
      <DialogContent className={styles.editDialog}>
        <DialogTitle>{editor?.type === "delete" ? "Delete study?" : "Rename study"}</DialogTitle>
        <DialogDescription>{editor?.type === "delete" ? `“${editor.study.title}” and its document, saved results and history will be permanently deleted. Archive it instead if you want to keep it.` : "Choose a name that makes this study easy to find."}</DialogDescription>
        <form onSubmit={event => void confirm(event)}>
          {editor?.type === "rename" && <input aria-label="Study name" value={title} onChange={event => setTitle(event.target.value)} maxLength={120} required disabled={!!busy}/>}
          {dialogError && <p role="alert" className={styles.error}>{dialogError}</p>}
          <div className={styles.actions}><button type="button" disabled={!!busy} onClick={() => setEditor(null)}>Cancel</button><button className={editor?.type === "delete" ? styles.deleteButton : styles.saveButton} disabled={!!busy || (editor?.type === "rename" && !title.trim())}>{busy ? "Saving…" : editor?.type === "delete" ? "Delete study" : "Save"}</button></div>
        </form>
      </DialogContent>
    </Dialog>
  </>;
}
