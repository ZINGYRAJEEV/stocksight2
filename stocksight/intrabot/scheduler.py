"""Session schedule — IST (NSE) and ET (US) phase windows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PhaseSpec:
    id: str
    label: str
    cest_label: str
    start_mins: int
    end_mins: int
    strategies: tuple[str, ...]
    allow_new_entries: bool = True
    manage_only: bool = False
    force_square_off: bool = False
    scan_only: bool = False


# IST minutes from midnight (NSE)
NSE_SCHEDULE: list[PhaseSpec] = [
    PhaseSpec("wake", "Wake-up — context", "05:30 CEST", 8 * 60, 9 * 60 + 15, (), allow_new_entries=False),
    PhaseSpec("gap_scan", "Gap Scanner", "05:45 CEST", 9 * 60 + 15, 9 * 60 + 20, ("GAP", "BROAD"), scan_only=True),
    PhaseSpec("mood", "Mood shortlist (top 3)", "05:50 CEST", 9 * 60 + 20, 9 * 60 + 30, ("GAP",), scan_only=True),
    PhaseSpec("open_scan", "Intraday breakout scan", "06:00 CEST", 9 * 60 + 30, 9 * 60 + 45, ("MOMENTUM", "GAP", "BROAD")),
    PhaseSpec("orb", "ORB + Momentum entries", "06:15 CEST", 9 * 60 + 45, 10 * 60 + 15, ("ORB", "MOMENTUM")),
    PhaseSpec("vwap_ath", "VWAP + ATH scan", "07:00 CEST", 10 * 60 + 30, 13 * 60, ("VWAP", "ATH")),
    PhaseSpec("lunch", "Lunch — monitor only", "09:00 CEST", 12 * 60 + 30, 15 * 60, (), manage_only=True),
    PhaseSpec("afternoon", "Afternoon momentum", "11:00 CEST", 14 * 60 + 30, 15 * 60 + 15, ("VWAP", "MOMENTUM", "BROAD")),
    PhaseSpec("square_off", "NSE square-off", "11:45 CEST", 15 * 60 + 15, 15 * 60 + 30, (), force_square_off=True),
]

# ET minutes (US)
US_SCHEDULE: list[PhaseSpec] = [
    PhaseSpec("pre_us", "Pre-US context", "—", 7 * 60, 9 * 60 + 30, (), allow_new_entries=False),
    PhaseSpec("us_gap", "NYSE gap + open scan", "09:30 CEST", 9 * 60 + 30, 10 * 60, ("GAP", "MOMENTUM", "ORB", "BROAD")),
    PhaseSpec("us_mid", "NYSE VWAP + ATH", "—", 10 * 60 + 30, 13 * 60 + 30, ("VWAP", "ATH")),
    PhaseSpec("us_lunch", "NYSE lunch monitor", "—", 12 * 60 + 30, 14 * 60, (), manage_only=True),
    PhaseSpec("us_afternoon", "NYSE afternoon", "15:30 CEST", 14 * 60 + 30, 15 * 60 + 55, ("VWAP", "BROAD", "MOMENTUM")),
    PhaseSpec("us_square_off", "NYSE square-off", "21:45 CEST", 15 * 60 + 55, 16 * 60 + 5, (), force_square_off=True),
]


def _now_mins(tz_name: str) -> int:
    from intraday import NSE_TZ, US_TZ, _now_tz

    tz = US_TZ if tz_name == "US" else NSE_TZ
    n = _now_tz(tz)
    return n.hour * 60 + n.minute


def resolve_phase(market: str, force_id: str = "") -> PhaseSpec:
    mkt = market.upper()
    phases = US_SCHEDULE if mkt == "US" else NSE_SCHEDULE
    if force_id:
        for p in phases:
            if p.id == force_id:
                return p
    mins = _now_mins(mkt)
    matched = [p for p in phases if p.start_mins <= mins < p.end_mins]
    if matched:
        return matched[-1]
    return PhaseSpec("off_hours", "Off schedule", "—", 0, 0, (), allow_new_entries=False)


def schedule_table(market: str) -> list[dict]:
    phases = US_SCHEDULE if market.upper() == "US" else NSE_SCHEDULE
    rows = []
    for p in phases:
        rows.append(
            {
                "Phase": p.id,
                "Label": p.label,
                "CEST note": p.cest_label,
                "Start": f"{p.start_mins // 60:02d}:{p.start_mins % 60:02d}",
                "End": f"{p.end_mins // 60:02d}:{p.end_mins % 60:02d}",
                "Strategies": ", ".join(p.strategies) or "—",
                "Entries": p.allow_new_entries and not p.manage_only,
            }
        )
    return rows
