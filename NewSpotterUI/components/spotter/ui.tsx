"use client"

import type React from "react"
import { cn } from "@/lib/utils"

/* Page title block shown at the top of each view */
export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="mb-6 flex items-end justify-between gap-4">
      <div>
        <h1 className="font-heading text-2xl font-bold tracking-wide text-foreground">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

/* A broadcast-style section header: a red tick + mono uppercase label */
export function SectionLabel({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <span className="h-3.5 w-1 rounded-full bg-primary" aria-hidden />
      <span className="label-mono text-[11px] font-medium text-muted-foreground">{children}</span>
    </div>
  )
}

/* The angled red accent plate used as a panel header in broadcast graphics */
export function Panel({
  label,
  action,
  children,
  className,
  bodyClassName,
}: {
  label?: React.ReactNode
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-card shadow-[0_1px_0_0_rgba(255,255,255,0.03)_inset]",
        className,
      )}
    >
      {(label || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-3.5">
          {label ? <SectionLabel>{label}</SectionLabel> : <span />}
          {action}
        </header>
      )}
      <div className={cn("p-5", bodyClassName)}>{children}</div>
    </section>
  )
}

/* iOS-style toggle in F1 red */
export function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label?: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-40",
        checked ? "bg-primary" : "bg-secondary",
      )}
    >
      <span
        className={cn(
          "inline-block h-4.5 w-4.5 transform rounded-full bg-white shadow transition-transform duration-200",
          checked ? "translate-x-5.5" : "translate-x-1",
        )}
      />
    </button>
  )
}

/* Range slider with F1-dark theme */
export function Slider({
  value,
  onChange,
  onPointerUp,
  min = 0,
  max = 100,
  label,
}: {
  value: number
  onChange: (v: number) => void
  onPointerUp?: (v: number) => void
  min?: number
  max?: number
  label?: string
}) {
  return (
    <input
      type="range"
      min={min}
      max={max}
      value={value}
      aria-label={label}
      onChange={(e) => onChange(Number(e.target.value))}
      onPointerUp={(e) => onPointerUp?.(Number((e.target as HTMLInputElement).value))}
      className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-secondary accent-primary"
    />
  )
}

/* Big data readout (speed / gear / position) */
export function Readout({
  label,
  value,
  unit,
  accent,
  className,
}: {
  label: string
  value: React.ReactNode
  unit?: string
  accent?: boolean
  className?: string
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="label-mono text-[10px] text-muted-foreground">{label}</span>
      <div className="flex items-baseline gap-1">
        <span
          className={cn(
            "font-heading text-3xl font-semibold leading-none tabular tracking-tight",
            accent ? "text-primary" : "text-foreground",
          )}
        >
          {value}
        </span>
        {unit && <span className="label-mono text-[10px] text-muted-foreground">{unit}</span>}
      </div>
    </div>
  )
}

/* Status dot */
export function Dot({
  state = "off",
  className,
}: {
  state?: "on" | "off" | "warn"
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-block h-2 w-2 rounded-full",
        state === "on" && "bg-success shadow-[0_0_8px_var(--success)]",
        state === "warn" && "bg-warning shadow-[0_0_8px_var(--warning)]",
        state === "off" && "bg-muted-foreground/40",
        className,
      )}
      aria-hidden
    />
  )
}

/* Tyre compound chip */
export function TyreChip({ compound }: { compound: string }) {
  const map: Record<string, string> = {
    S: "border-primary/60 text-primary",
    M: "border-warning/60 text-warning",
    H: "border-foreground/40 text-foreground",
    I: "border-success/60 text-success",
    W: "border-[#3671C6]/60 text-[#5b8fe0]",
  }
  return (
    <span
      className={cn(
        "inline-flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-bold font-mono",
        map[compound] ?? "border-border text-muted-foreground",
      )}
    >
      {compound}
    </span>
  )
}

/* Keyboard key cap */
export function KeyCap({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-7 min-w-7 items-center justify-center rounded-md border border-border bg-elevated px-2 font-mono text-[11px] font-semibold text-foreground shadow-[0_2px_0_0_rgba(0,0,0,0.4)]">
      {children}
    </kbd>
  )
}
