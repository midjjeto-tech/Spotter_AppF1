"use client"

export function StatusBar({
  persona,
  speaker,
}: {
  persona?: string
  speaker?: string
}) {
  const items = [
    { label: "ПЕРСОНА", value: persona ?? "—" },
    // Реально звучащий спикер: «Яндекс: Филипп» / «Piper: Ruslan».
    // НЕ подменяется на дефолтный Piper, когда активен Yandex.
    { label: "ГОЛОС", value: speaker ?? "—" },
  ]
  return (
    <footer className="flex h-8 shrink-0 items-center justify-between border-t border-border bg-card px-6">
      <div className="flex items-center gap-2">
        <span className="label-mono text-[11px] text-muted-foreground/70">SPOTTER</span>
        <span className="font-mono text-[11px] text-muted-foreground">v1.0.0</span>
      </div>
      <div className="flex items-center gap-6">
        {items.map((i) => (
          <div key={i.label} className="hidden items-center gap-2 md:flex">
            <span className="label-mono text-[11px] text-muted-foreground/70">{i.label}</span>
            <span className="font-mono text-[11px] text-foreground">{i.value}</span>
          </div>
        ))}
      </div>
    </footer>
  )
}
