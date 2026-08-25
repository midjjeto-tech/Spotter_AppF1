"use client"

import { PhoneView } from "@/components/spotter/views/phone"

// Отдельный маршрут радиопульта — `webui/phone.html`, ровно как у игрового
// оверлея (`app/overlay/page.tsx` → `webui/overlay.html`). Ссылку на него
// отдаёт панель «Радиопульт» (core/engine.py::get_remote_access_info).
export default function PhonePage() {
  return <PhoneView />
}
