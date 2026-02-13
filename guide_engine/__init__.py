from .models import GuideRequest, GuideResponse, GuideReference


def __getattr__(name: str):
    if name in ("GuideService", "get_guide_service"):
        from .guide_service import GuideService, get_guide_service

        globals()["GuideService"] = GuideService
        globals()["get_guide_service"] = get_guide_service
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "GuideService",
    "get_guide_service",
    "GuideRequest",
    "GuideResponse",
    "GuideReference",
]
