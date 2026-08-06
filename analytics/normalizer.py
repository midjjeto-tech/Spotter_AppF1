from __future__ import annotations
import math

def _td_to_ms(td) -> int | None:
    try:
        if td is None: return None
        if hasattr(td, 'isnull') and td.isnull(): return None
        total = td.total_seconds()
        return None if math.isnan(total) else int(total * 1000)
    except Exception: return None

def _safe_int(v) -> int | None:
    try:
        f = float(v)
        return None if math.isnan(f) else int(f)
    except Exception: return None

def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 3)
    except Exception: return None

def _weather(session) -> dict:
    out = {"air_temp": None, "track_temp": None, "rainfall": None}
    try:
        w = session.weather_data
        if w is not None and not w.empty:
            row = w.iloc[len(w) // 2]
            out["air_temp"] = _safe_float(row.get("AirTemp"))
            out["track_temp"] = _safe_float(row.get("TrackTemp"))
            out["rainfall"] = bool(row.get("Rainfall", False))
    except Exception: pass
    return out

def _results(session) -> list[dict]:
    out = []
    try:
        res = session.results
        if res is None or res.empty: return out
        for _, row in res.iterrows():
            pos = _safe_int(row.get("Position"))
            if pos is None: continue
            gap = None
            try:
                t = row.get("Time")
                if pos > 1 and t is not None and hasattr(t, "total_seconds"):
                    gap = _safe_float(t.total_seconds())
            except Exception: pass
            out.append({"pos": pos,
                        "driver": str(row.get("Abbreviation", "?")),
                        "team": str(row.get("TeamName", "?")),
                        "gap_s": gap,
                        "fastest_lap_ms": _td_to_ms(row.get("FastestLapTime"))})
        out.sort(key=lambda r: r["pos"])
    except Exception: pass
    return out

def _fastest_lap(session) -> dict:
    out = {"driver": None, "lap": None, "time_ms": None,
           "s1_ms": None, "s2_ms": None, "s3_ms": None}
    try:
        laps = session.laps
        if laps is None or laps.empty: return out
        fl = laps.pick_fastest()
        if fl is None or (hasattr(fl, 'empty') and fl.empty): return out
        out.update({"driver": str(fl.get("Driver", "?")),
                    "lap": _safe_int(fl.get("LapNumber")),
                    "time_ms": _td_to_ms(fl.get("LapTime")),
                    "s1_ms": _td_to_ms(fl.get("Sector1Time")),
                    "s2_ms": _td_to_ms(fl.get("Sector2Time")),
                    "s3_ms": _td_to_ms(fl.get("Sector3Time"))})
    except Exception: pass
    return out

def _best_sectors(session) -> dict:
    out = {"s1_ms": None, "s2_ms": None, "s3_ms": None}
    try:
        laps = session.laps
        if laps is None or laps.empty: return out
        for col, key in [("Sector1Time","s1_ms"),("Sector2Time","s2_ms"),("Sector3Time","s3_ms")]:
            valid = laps[col].dropna()
            if not valid.empty: out[key] = _td_to_ms(valid.min())
    except Exception: pass
    return out

def _safety_cars(session) -> int:
    try:
        msgs = session.race_control_messages
        if msgs is None or msgs.empty: return 0
        sc = msgs[msgs["Message"].str.contains("SAFETY CAR", na=False, case=False)]
        dep = sc[sc["Message"].str.contains("DEPLOYED", na=False, case=False)]
        return len(dep) if not dep.empty else (1 if not sc.empty else 0)
    except Exception: return 0

def _penalties(session) -> int:
    try:
        msgs = session.race_control_messages
        if msgs is None or msgs.empty: return 0
        pen = msgs[msgs["Message"].str.contains(
            r"PENALTY|TIME PENALTY|DRIVE THROUGH|STOP AND GO", na=False, case=False)]
        return len(pen)
    except Exception: return 0

def normalize(session) -> dict:
    """FastF1 Session → plain dict. Never raises."""
    try:
        event = str(session.event.get("EventName", None))
        year = _safe_int(session.event.year)
        sname = str(session.name)
    except Exception:
        event = year = sname = None
    results = _results(session)
    return {
        "event": event, "year": year, "session": sname,
        "weather": _weather(session),
        "total_results_count": len(results),
        "results_top10": results[:10],
        "results": results,
        "fastest_lap": _fastest_lap(session),
        "best_sectors": _best_sectors(session),
        "safety_cars": _safety_cars(session),
        "penalties": _penalties(session),
    }
