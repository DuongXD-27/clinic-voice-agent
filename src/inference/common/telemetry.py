"""Small timing primitive shared by inference adapters."""

from time import perf_counter


class InferenceTimer:
    def __init__(self) -> None:
        self._started = perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return (perf_counter() - self._started) * 1000
