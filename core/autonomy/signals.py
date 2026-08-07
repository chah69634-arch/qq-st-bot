"""Compatibility import surface for proactive signal adapters."""

from core.autonomy.models import ProactiveSignal, Signal, merge_signal_candidates
from core.autonomy.signal_adapters import *

__all__ = [
    "ProactiveSignal", "Signal", "merge_signal_candidates",
    "adapt_routine", "adapt_time_background", "adapt_heart_rate",
    "adapt_memory_reactivation", "adapt_topic_followup", "adapt_desktop_wake",
    "enqueue_desktop_wake_signal", "adapt_restart", "adapt_trigger",
    "collect_external_signals", "emit_trigger_signal",
    "registered_signal_adapter",
]
