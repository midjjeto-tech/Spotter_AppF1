const AVATAR_BY_ID: Record<string, string> = {
  race_control: "/racefeed/avatars/race-control.svg",
  // Qualifying desk is the same "official timing" voice — reuse the Race
  // Control face rather than ship a near-duplicate asset.
  qualifying_control: "/racefeed/avatars/race-control.svg",
  spotter_analytics: "/racefeed/avatars/spotter-analytics.svg",
  // Новые редакции переиспользуют существующие лица: чемпионат/достижения —
  // «официальный» голос дирекции, паддок — репортёр из боксов.
  championship_desk: "/racefeed/avatars/race-control.svg",
  achievements: "/racefeed/avatars/race-control.svg",
  paddock: "/racefeed/avatars/players-garage.svg",
  players_garage: "/racefeed/avatars/players-garage.svg",
  apex_nerd: "/racefeed/avatars/apex-nerd.svg",
  sector_times: "/racefeed/avatars/sector-times.svg",
  grandstand: "/racefeed/avatars/grandstand.svg",
  pitwall: "/racefeed/avatars/pitwall.svg",
  late_braker: "/racefeed/avatars/late-braker.svg",
  tyre_whisperer: "/racefeed/avatars/tyre-whisperer.svg",
}

export function getRaceFeedAvatar(id: string) {
  return AVATAR_BY_ID[id] ?? "/racefeed/avatars/grandstand.svg"
}
