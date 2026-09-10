import html


def page(title, body):
    return f'''<!doctype html><html lang="en"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
    <style>
    *{{box-sizing:border-box}}body{{margin:0;background:#f4f6fa;color:#25334b;font:14px/1.6 system-ui,sans-serif}}
    main{{max-width:1320px;margin:auto;padding:48px 36px}}.eyebrow{{font-size:11px;letter-spacing:3px;color:#8190a3}}
    h1{{font-size:32px;font-weight:500;letter-spacing:-1px;margin:10px 0 16px;overflow-wrap:anywhere}}
    h2{{font-size:15px;font-weight:500}}a{{color:#5364bc;text-decoration:none}}a:hover{{color:#273978}}
    .badge{{display:inline-block;padding:3px 10px;border-radius:20px;background:#e7efe9;color:#527262;font-size:11px}}
    .fail{{background:#f5e8ec;color:#ad5267}}.muted{{color:#8190a3}}.card{{background:#fff;border:1px solid #e5e9f0;border-radius:16px;overflow:hidden;margin:24px 0}}
    .card header{{padding:18px 24px;border-bottom:1px solid #eef1f6;display:flex;justify-content:space-between;gap:12px}}
    img{{display:block;width:100%;height:auto}}nav{{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}}nav a{{background:white;padding:9px 16px;border:1px solid #e5e9f0;border-radius:8px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:24px}}.grid .card{{margin:0}}.grid h2{{margin:0;overflow-wrap:anywhere}}
    @media(max-width:600px){{main{{padding:24px 16px}}h1{{font-size:24px}}}}
    </style><main><div class="eyebrow">NEUTRAL ATOM LAB / MILESTONE 0</div>{body}</main></html>'''



def render(snapshot, path, theme=None):
    """Compatibility entry point; all drawings use the shared scene renderer."""
    from .renderer import render_layout
    from .theme import VisualTheme
    if isinstance(theme, dict):
        theme = VisualTheme(**{k:v for k,v in theme.items() if k != 'grid_spacing_um'})
    render_layout(snapshot, path, theme=theme)
