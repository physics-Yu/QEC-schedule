"""Finite endpoint search over half-open resource intervals, not binder retries."""
from copy import deepcopy
import math

from .errors import RuntimeContractError


def require(ok, code, message):
    if not ok:
        raise RuntimeContractError(code, message)


def finite(value, label):
    require(type(value) in (int, float) and math.isfinite(value), "CALENDAR_TIME", f"{label} must be finite")
    return float(value)


class ResourceCalendar:
    def __init__(self, capacities=None):
        self.capacities = deepcopy(capacities or {})
        require(all(type(n) is int and n > 0 for n in self.capacities.values()), "RESOURCE_CAPACITY", "Resource capacities must be positive integers")
        self._leases = {}
        self._owners = set()
        self.floor_us = 0.0
        self.stats = {"candidate_points_checked": 0, "interval_comparisons": 0, "event_sweep_steps": 0, "reservations": 0, "retired_intervals": 0}

    def _profile(self, intervals):
        result = []
        require(isinstance(intervals, list), "RESOURCE_INTERVALS", "Resource profile must be a list")
        for interval in intervals:
            i = deepcopy(interval)
            require(isinstance(i.get("resource_id"), str) and i["resource_id"], "RESOURCE_ID", "Every interval needs a resource identity")
            a, b = finite(i.get("start_us"), "start_us"), finite(i.get("end_us"), "end_us")
            require(0 <= a < b, "RESOURCE_INTERVAL", "Relative intervals need 0 <= start < end")
            units = i.get("units", 1)
            require(type(units) is int and 0 < units <= self.capacities.get(i["resource_id"], 1), "RESOURCE_CAPACITY", "Requested units exceed the declared resource capacity")
            share = i.get("share_key")
            require(share is None or isinstance(share, str) and bool(share), "RESOURCE_SHARE_KEY", "Explicit joint operation keys must be nonempty strings")
            result.append(dict(i, start_us=a, end_us=b, units=units))
        return result

    def conflicts(self, intervals, start_us):
        profile = self._profile(intervals)
        start = finite(start_us, "start_us")
        require(start >= self.floor_us, "CALENDAR_REWIND", "Cannot reserve before the committed calendar floor")
        by_resource = {}
        for index, interval in enumerate(profile):
            absolute = dict(interval, start_us=start+interval["start_us"], end_us=start+interval["end_us"], owner="candidate", index=index)
            by_resource.setdefault(interval["resource_id"], []).append(absolute)
        conflicts = []
        for resource, new in by_resource.items():
            lo, hi = min(i["start_us"] for i in new), max(i["end_us"] for i in new)
            old = []
            for i in self._leases.get(resource, []):
                self.stats["interval_comparisons"] += 1
                if i["end_us"] > lo:
                    self.stats["interval_comparisons"] += 1
                    if i["start_us"] < hi: old.append(i)
            # Exact shared actions are one occupancy group. Sweep starts/ends
            # once instead of rescanning every interval at every endpoint.
            grouped = {}
            for index, i in enumerate([*old, *new]):
                key = ("shared", i["share_key"], i["start_us"], i["end_us"], i["units"]) if i.get("share_key") else ("single", index)
                g = grouped.setdefault(key, {"start": i["start_us"], "end": i["end_us"], "units": i["units"], "owners": set(), "new": False})
                g["owners"].add(i["owner"]); g["new"] |= index >= len(old)
            events = {}
            for key, g in grouped.items():
                events.setdefault(g["start"], {"starts": [], "ends": []})["starts"].append(key)
                events.setdefault(g["end"], {"starts": [], "ends": []})["ends"].append(key)
            endpoints = sorted(events)
            active, load, new_count = set(), 0, 0
            for a, b in zip(endpoints, endpoints[1:]):
                for key in events[a]["ends"]:
                    active.remove(key); load -= grouped[key]["units"]; new_count -= int(grouped[key]["new"])
                    self.stats["event_sweep_steps"] += 1
                for key in events[a]["starts"]:
                    active.add(key); load += grouped[key]["units"]; new_count += int(grouped[key]["new"])
                    self.stats["event_sweep_steps"] += 1
                if new_count and load > self.capacities.get(resource, 1):
                    conflicts.append({"resource_id": resource, "start_us": a, "end_us": b, "load": load,
                                      "capacity": self.capacities.get(resource, 1), "owners": sorted({o for key in active for o in grouped[key]["owners"]})})
        return conflicts

    def earliest_start(self, intervals, earliest_us, *, feasible_start_intervals=None):
        profile = self._profile(intervals)
        earliest = max(self.floor_us, finite(earliest_us, "earliest_us"))
        # Exact changes in feasibility occur at endpoint differences; synchronized
        # operations additionally allow isolated coincident-start candidates.
        candidates = {earliest}
        for interval in profile:
            for lease in self._leases.get(interval["resource_id"], []):
                boundary = lease["end_us"]-interval["start_us"]
                if boundary >= earliest: candidates.add(boundary)
                if interval.get("share_key") == lease.get("share_key") and interval.get("share_key"):
                    alignment = lease["start_us"]-interval["start_us"]
                    if alignment >= earliest: candidates.add(alignment)
        windows = feasible_start_intervals
        if windows is not None:
            require(isinstance(windows, list), "FEASIBLE_WINDOWS", "Feasible start windows must be explicit")
            normalized = []
            for w in windows:
                lo = finite(w["start_us"], "window.start_us")
                hi = None if w.get("end_us") is None else finite(w["end_us"], "window.end_us")
                require(lo >= 0 and (hi is None or hi >= lo), "FEASIBLE_WINDOWS", "Invalid feasible window")
                normalized.append((lo, hi))
                candidates.add(max(earliest, lo))
            windows = normalized
        for start in sorted(candidates):
            if windows is not None and not any(lo <= start and (hi is None or start <= hi) for lo, hi in windows):
                continue
            self.stats["candidate_points_checked"] += 1
            if not self.conflicts(profile, start):
                return start
        raise RuntimeContractError("NO_FEASIBLE_RESOURCE_WINDOW", "No start in the declared interval domain; this is not a routing infeasibility proof")

    def reserve(self, owner, intervals, start_us):
        require(isinstance(owner, str) and owner and owner not in self._owners, "LEASE_OWNER_REUSE", "Reservation owners must be unique")
        profile = self._profile(intervals)
        conflicts = self.conflicts(profile, start_us)
        if conflicts:
            error = RuntimeContractError("RESOURCE_CONFLICT", "Requested window exceeds shared resource capacity")
            error.details = conflicts
            raise error
        affected = set()
        for i in profile:
            lease = dict(i, owner=owner, start_us=i["start_us"]+start_us, end_us=i["end_us"]+start_us)
            self._leases.setdefault(i["resource_id"], []).append(lease)
            affected.add(i["resource_id"])
        for resource in affected: self._leases[resource].sort(key=lambda item: (item["start_us"], item["end_us"], item["owner"]))
        self._owners.add(owner)
        self.stats["reservations"] += 1

    def advance_floor(self, time_us):
        now = finite(time_us, "time_us")
        require(now >= self.floor_us, "CALENDAR_REWIND", "Calendar frontier cannot move backward")
        for resource, leases in list(self._leases.items()):
            kept = [i for i in leases if i["end_us"] > now]
            self.stats["retired_intervals"] += len(leases)-len(kept)
            if kept: self._leases[resource] = kept
            else: del self._leases[resource]
        self.floor_us = now

    def snapshot(self):
        return {"schema_version": "resource-calendar/0.1", "capacities": deepcopy(self.capacities), "floor_us": self.floor_us,
                "leases": deepcopy(self._leases), "owners": sorted(self._owners), "stats": deepcopy(self.stats)}

    @classmethod
    def restore(cls, data):
        require(data.get("schema_version") == "resource-calendar/0.1", "CALENDAR_SCHEMA", "Unknown calendar checkpoint")
        obj = cls(data["capacities"])
        obj.floor_us = data["floor_us"]
        obj._leases = deepcopy(data["leases"])
        obj._owners = set(data["owners"])
        obj.stats.update(deepcopy(data["stats"]))
        return obj
