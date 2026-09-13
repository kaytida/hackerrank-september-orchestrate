from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from config import EXCHANGE_RATES_PATH


@dataclass(frozen=True)
class ExchangeRateTable:
    """Fixed dated rates from dataset/exchange_rates.csv."""

    # (rate_date, from_currency, to_currency) -> rate where 1 FROM = rate * TO
    _rates: dict[tuple[str, str, str], float]
    _dates: list[str]

    @classmethod
    def load(cls, path: Path | None = None) -> "ExchangeRateTable":
        """Load dated FX rates from exchange_rates.csv."""
        csv_path = path or EXCHANGE_RATES_PATH
        rates: dict[tuple[str, str, str], float] = {}
        dates: set[str] = set()
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["rate_date"], row["from_currency"], row["to_currency"])
                rates[key] = float(row["rate"])
                dates.add(row["rate_date"])
        return cls(_rates=rates, _dates=sorted(dates))

    def _rate_on_or_before(self, from_currency: str, to_currency: str, on_date: str) -> float | None:
        """Latest direct rate on or before on_date, or None."""
        if from_currency == to_currency:
            return 1.0
        best_rate: float | None = None
        best_date = ""
        for rate_date in self._dates:
            if rate_date > on_date:
                continue
            key = (rate_date, from_currency, to_currency)
            if key not in self._rates:
                continue
            if rate_date >= best_date:
                best_date = rate_date
                best_rate = self._rates[key]
        return best_rate

    def _inverse_on_or_before(self, from_currency: str, to_currency: str, on_date: str) -> float | None:
        """Derive rate via inverse pair when direct quote is missing."""
        direct = self._rate_on_or_before(to_currency, from_currency, on_date)
        if direct is None or direct == 0:
            return None
        return 1.0 / direct

    def convert(self, amount: float, from_currency: str, to_currency: str, on_date: str) -> float:
        """Convert amount using direct, inverse, or USD/EUR bridge rates on or before on_date."""
        if from_currency == to_currency:
            return amount
        direct = self._rate_on_or_before(from_currency, to_currency, on_date)
        if direct is not None:
            return amount * direct
        inverse = self._inverse_on_or_before(from_currency, to_currency, on_date)
        if inverse is not None:
            return amount * inverse
        for bridge in ("USD", "EUR"):
            if bridge in (from_currency, to_currency):
                continue
            leg1 = self._rate_on_or_before(from_currency, bridge, on_date)
            if leg1 is None:
                leg1 = self._inverse_on_or_before(from_currency, bridge, on_date)
            leg2 = self._rate_on_or_before(bridge, to_currency, on_date)
            if leg2 is None:
                leg2 = self._inverse_on_or_before(bridge, to_currency, on_date)
            if leg1 is not None and leg2 is not None:
                return amount * leg1 * leg2
        raise ValueError(
            f"No exchange rate path for {from_currency}->{to_currency} on or before {on_date}"
        )
