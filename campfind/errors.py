"""Errors a caller can catch."""


class CampfindError(Exception):
    """The lookup could not be completed."""


class ParkNotFound(CampfindError):
    """No park matched the name or id."""


class AmbiguousPark(CampfindError):
    """More than one park matched."""

    def __init__(self, query: str, names: list[str]):
        self.query = query
        self.names = names
        listed = ", ".join(names)
        super().__init__(f"'{query}' matches more than one park: {listed}")
