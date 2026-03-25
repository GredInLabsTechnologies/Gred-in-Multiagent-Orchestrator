from __future__ import annotations

from ._base import OpsServiceBase
from ._telemetry import TelemetryMixin
from ._plan import PlanConfigMixin
from ._draft import DraftMixin
from ._approved import ApprovedMixin
from ._run import RunMixin
from ._lock import LockMixin


class OpsService(
    TelemetryMixin,
    PlanConfigMixin,
    DraftMixin,
    ApprovedMixin,
    RunMixin,
    LockMixin,
    OpsServiceBase,
):
    """Composite OpsService assembled from domain mixins.
    
    **Authority of drafts, approved, runs, and locks.**

    Method resolution order ensures that ``cls`` in every mixin
    resolves to this final class, which carries all class variables
    defined in ``OpsServiceBase``.
    """

    pass
