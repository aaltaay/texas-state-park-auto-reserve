"""Fast campsite availability lookup.

This package only reads public availability. It does not sign in, hold a site,
or take payment.
"""

from campfind.models import AvailabilityResult
from campfind.search import search

__all__ = ["AvailabilityResult", "search"]
__version__ = "0.1.0"
