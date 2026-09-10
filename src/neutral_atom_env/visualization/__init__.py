"""Read-only visualization integration. No scheduling or physical state writes."""
from .recording import VisualRecorder
from .viewer import write_html,write_bundle
from .summary import summarize_trace,render_summary

__all__=['VisualRecorder','write_html','write_bundle','summarize_trace','render_summary']
