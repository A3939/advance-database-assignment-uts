"use client";

import { Select } from "radix-ui";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import styles from "./select-field.module.css";

export type SelectOption = { value: string; label: string; disabled?: boolean };

/** A shared application menu, including explicit empty-value choices such as “All”. */
export function SelectField({ value, onValueChange, options, placeholder = "Select…", disabled, compact, className = "", ...triggerProps }: {
  value: string;
  onValueChange: (value: string) => void;
  options: readonly SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  compact?: boolean;
  className?: string;
  "aria-label": string;
  "aria-describedby"?: string;
  id?: string;
}) {
  // Radix reserves the empty string for its placeholder. Encoding every option
  // preserves real empty choices without colliding with a resource's ID.
  const encode = (raw: string) => `value:${raw}`;
  const selected = options.some(option => option.value === value);
  return <Select.Root value={selected ? encode(value) : ""} disabled={disabled || !options.length}
    onValueChange={next => {
      const option = options.find(item => encode(item.value) === next);
      if (option && !option.disabled) onValueChange(option.value);
    }}>
    <Select.Trigger {...triggerProps} type="button" className={`${styles.trigger} ${className}`} data-compact={compact || undefined}>
      <Select.Value placeholder={placeholder}/>
      <Select.Icon className={styles.chevron}><ChevronDown size={15}/></Select.Icon>
    </Select.Trigger>
    <Select.Portal>
      <Select.Content className={styles.menu} position="popper" align="start" sideOffset={6} collisionPadding={12}>
        <Select.ScrollUpButton className={styles.scroll}><ChevronUp size={14}/></Select.ScrollUpButton>
        <Select.Viewport className={styles.viewport}>
          {options.map(option => <Select.Item key={option.value} value={encode(option.value)} textValue={option.label} disabled={option.disabled} className={styles.option}>
            <Select.ItemText>{option.label}</Select.ItemText>
            <Select.ItemIndicator className={styles.check}><Check size={15}/></Select.ItemIndicator>
          </Select.Item>)}
        </Select.Viewport>
        <Select.ScrollDownButton className={styles.scroll}><ChevronDown size={14}/></Select.ScrollDownButton>
      </Select.Content>
    </Select.Portal>
  </Select.Root>;
}
