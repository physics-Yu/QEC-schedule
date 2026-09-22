"""Zoned compiler: logical schedule -> placement -> batches -> physical codegen.

Inspired by MQT QMAP's bounded layer-wise search, adapted to this platform's
SLM-anchor/AOD-mobile CZ contract. No dependency on QMAP or demo protocols.
"""
from .controller import run_zoned
from .interaction import InteractionCompiler, ResolvedInteraction, LoweredInteraction

__all__ = ['run_zoned', 'InteractionCompiler', 'ResolvedInteraction', 'LoweredInteraction']
