"use client";

import { Select } from "radix-ui";
import { Check, ChevronDown } from "lucide-react";
import type { SourceSelection } from "@/services/contracts";
import { sourceDisplayName } from "@/services/catalog-contracts";

import { useWorkspace } from "./workspace";

export default function SourceSelect({ value, onChange }: {
  value: SourceSelection;
  onChange: (source: SourceSelection) => void;
}) {
  const {catalog} = useWorkspace();
  const sources = [{value:"All",label:"All",name:"All sources"}, ...catalog.sources.map(s=>({value:s.source,label:sourceDisplayName(s,catalog),name:s.title}))];
  return (
    <div className="source-select">
      <span>Source</span>
      <Select.Root value={value} onValueChange={next => {
        const source = sources.find(item => item.value === next);
        if (source) onChange(source.value as SourceSelection);
      }}>
        <Select.Trigger className="source-trigger" aria-label="Data source">
          <Select.Value />
          <Select.Icon className="source-chevron"><ChevronDown size={15} /></Select.Icon>
        </Select.Trigger>
        <Select.Portal>
          <Select.Content className="source-menu" position="popper" align="end"
            sideOffset={8} collisionPadding={12}>
            <Select.Viewport>
              {sources.map(source => (
                <Select.Item key={source.value} className="source-option" value={source.value}
                  aria-label={source.label} textValue={`${source.label} ${source.name}`}>
                  <span className="source-option-copy">
                    <Select.ItemText>{source.label}</Select.ItemText>
                    <span className="source-option-description">{source.name}</span>
                  </span>
                  <Select.ItemIndicator className="source-option-check"><Check size={16} /></Select.ItemIndicator>
                </Select.Item>
              ))}
            </Select.Viewport>
          </Select.Content>
        </Select.Portal>
      </Select.Root>
    </div>
  );
}
