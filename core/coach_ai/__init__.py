try:
    from core.coach_ai.analyzer import DriverCoach
    __all__ = ["DriverCoach"]
except ImportError:
    # analyzer.py not yet implemented
    __all__ = []
