from dataclasses import dataclass, asdict
import json
from pathlib import Path


@dataclass(frozen=True)
class VisualTheme:
    static_color: str = '#5364bc'
    moving_color: str = '#e89438'
    active_color: str = '#d95360'
    failure_color: str = '#bd5362'
    zone_colors: tuple[str, ...] = ('#eef3f5', '#f0edf8', '#eaf3ef')
    grid_color: str = '#dbe2e9'
    text_color: str = '#25334b'
    muted_color: str = '#8190a3'
    background: str = '#fafbfd'
    font_size: float = 10
    atom_size: float = 24
    trap_size: float = 64
    grid_line_width: float = .45
    atom_label_size: float = 6
    ready_color: str = '#e5eafc'
    blocked_color: str = '#f0f2f5'
    completed_color: str = '#e5f2ea'

    @classmethod
    def load(cls, path=None):
        if path is None:
            path = Path(__file__).resolve().parents[3] / 'configs/visual/default.json'
        data = json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else {}
        data.pop('grid_spacing_um', None)  # geometry belongs to world config
        if 'zone_colors' in data:
            data['zone_colors'] = tuple(data['zone_colors'])
        return cls(**data)

    def colors(self):
        return asdict(self)
