from dataclasses import dataclass


@dataclass(frozen=True)
class PlacementChoice:
    gate_id: str
    anchor: str
    mobile: str
    site: str
    x: float
    y: float

    @property
    def assignment(self):
        return (self.gate_id, self.anchor, self.mobile, self.x, self.y)


@dataclass(frozen=True)
class LayerPlacement:
    choices: tuple[PlacementChoice, ...]
    estimated_cost: float
    staging: tuple[tuple[str, str], ...] = ()

    @property
    def destinations(self):
        return dict(self.staging, **{c.anchor: c.site for c in self.choices})
