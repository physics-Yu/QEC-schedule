"""Repackage an existing gallery's embedded motion; never import the compiler."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def refresh(out):
    out = Path(out)
    from export_viewer_regions import export as export_regions
    export_regions(out)
    previous = (out / 'full-viewer.html').read_text(encoding='utf-8')
    packed = re.findall(r'<script type="application/octet-stream" id="packed-[^"]+">[^<]+</script>', previous)
    if len(packed) != 71:
        raise ValueError('EXPECTED_EXISTING_71_DATASETS')
    projection_hash = hashlib.sha256(''.join(packed).encode()).hexdigest()
    shell = (ROOT / 'viewer/components.html').read_text(encoding='utf-8')
    (out / 'index.html').write_text(shell, encoding='utf-8')
    for name in ('components.css', 'components.js', 'motion-preview.js', 'resource-schedule.js', 'lab-renderer.js'):
        shutil.copyfile(ROOT / 'viewer' / name, out / name)
    standalone = shell.replace('<link rel="stylesheet" href="components.css">', '<style>' + (out / 'components.css').read_text(encoding='utf-8') + '</style>')
    standalone = standalone.replace('<script src="manifest.js"></script>', ''.join(packed) + '<script>' + (out / 'manifest.js').read_text(encoding='utf-8') + '</script>')
    for name in ('schedules.js', 'regions.js', 'motion-preview.js', 'resource-schedule.js', 'lab-renderer.js', 'components.js'):
        standalone = standalone.replace(f'<script src="{name}"></script>', '<script>' + (out / name).read_text(encoding='utf-8') + '</script>')
    (out / 'full-viewer.html').write_text(standalone, encoding='utf-8')
    # A distinct entry URL opens the directory even if an old tab retained #CZ.
    shutil.copyfile(out / 'full-viewer.html', out / 'animation-library.html')
    receipt = {
        'schema_version': 'ViewerPresentation/0.6', 'components': 71,
        'file': 'full-viewer.html', 'sha256': hashlib.sha256((out / 'full-viewer.html').read_bytes()).hexdigest(),
        'embedded_datasets_unchanged_sha256': projection_hash, 'compiler_invoked': False,
        'original_compilation_acceptance': 'revisions/before-atom-brightness/acceptance.json' if (out / 'revisions/before-atom-brightness/acceptance.json').is_file() else 'revisions/before-timed-xy-viewer/acceptance.json' if (out / 'revisions/before-timed-xy-viewer/acceptance.json').is_file() else 'acceptance.json',
        'original_accepted_window': 'revisions/before-atom-brightness/animation-library.html' if (out / 'revisions/before-atom-brightness/animation-library.html').is_file() else 'revisions/before-timed-xy-viewer/full-viewer.html' if (out / 'revisions/before-timed-xy-viewer/full-viewer.html').is_file() else None,
        'time_modes': ['keyframe', 'physical'], 'default_mode': 'physical',
        'physical_rate': 'fixed us/s times selected playback speed, including 1000000 us/s for original time',
        'movement_interface': {'from': 'A: (x,y) um', 'to': 'B: (x,y) um', 'start_us': 'source', 'end_us': 'source', 'batch': 'same compiled action'},
        'xy_path': 'display only; synchronised axis segments, analytically checked pair distances, original fallback explicit',
        'clearance_um': {'default': 1, 'kind': 'display threshold, not hardware calibration'},
        'original_times_endpoints_results_and_programs_modified': False,
        'hardware_route_qualified': False, 'browser_rendering_verified': False,
        'user_visual_acceptance': 'pending',
        'navigation': 'component directory -> canvas studio -> return to directory',
        'entry_file': 'animation-library.html',
        'scene_scaling': 'one world transform scales all physical glyphs, strokes, fields and labels',
        'transfers': 'atom body emission follows AOD occupancy: SLM dim, pickup smooth brightening, AOD bright including stationary CZ, drop smooth dimming; recorded intervals preserved',
        'transfer_inspection': 'carrier counts, direction, parallel atom count, progress, remaining model and screen time, explicit jump-to-end',
        'CZ_illumination': 'compute zone red only during the completed CZ action interval with gate and zone display enabled',
        'atom_marker_scene_radius_um': 2.8,
        'ancilla_colors': {'X': '#537880', 'Z': '#648c6e'},
        'default_style': 'reference',
        'default_glow': False,
        'default_atom_carrier_brightness': True,
        'brightness_semantics': 'carrier display only, not calibrated fluorescence or laser power',
        'default_trails': False,
        'zone_geometry_source': 'regions.js projected from frozen device zones',
        'physical_default_us_per_screen_second': 100,
        'resource_schedule': 'schedules.js, exported only from original action resources and event status',
    }
    (out / 'viewer-presentation.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'components': 71, 'compiler_invoked': False, 'path': str((out / 'full-viewer.html').resolve())}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    refresh(parser.parse_args().out)
