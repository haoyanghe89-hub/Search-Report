from datetime import date

from ..domain import Instrument, InstrumentAlias, InstrumentStatus, TradingRule


class InstrumentMaster:
    def __init__(self, instruments: tuple[Instrument, ...] = ()) -> None:
        self._items: dict[str, Instrument] = {}
        for instrument in instruments:
            self.add(instrument)

    def add(self, instrument: Instrument) -> None:
        if instrument.instrument_id in self._items:
            if self._items[instrument.instrument_id] != instrument:
                raise ValueError("immutable instrument ID already registered")
            return
        for existing in self._items.values():
            for left in existing.aliases:
                for right in instrument.aliases:
                    if (left.exchange, left.code) == (right.exchange, right.code):
                        if max(left.valid_from, right.valid_from) <= min(
                            left.valid_to or date.max, right.valid_to or date.max
                        ):
                            raise ValueError("overlapping code alias lifecycle")
        self._items[instrument.instrument_id] = instrument

    def get(self, instrument_id: str) -> Instrument:
        return self._items[instrument_id]

    def alias(self, instrument_id: str, on: date) -> InstrumentAlias:
        item = self.get(instrument_id)
        if on < item.listed_at or (item.delisted_at is not None and on > item.delisted_at):
            raise ValueError("instrument outside lifecycle")
        matches = [
            alias
            for alias in item.aliases
            if alias.valid_from <= on and (alias.valid_to is None or on <= alias.valid_to)
        ]
        if len(matches) != 1:
            raise ValueError("ambiguous or unavailable effective alias")
        return matches[0]

    def status(self, instrument_id: str, on: date) -> InstrumentStatus | None:
        matches = [
            state
            for state in self.get(instrument_id).statuses
            if state.effective_from <= on
            and (state.effective_to is None or on <= state.effective_to)
        ]
        if len(matches) > 1:
            raise ValueError("ambiguous status history")
        return matches[0] if matches else None  # unknown is not 'normal'

    def rule(self, instrument_id: str, on: date, status: str) -> TradingRule:
        item = self.get(instrument_id)
        alias = self.alias(instrument_id, on)
        matches = [
            rule
            for rule in item.rules
            if rule.exchange == alias.exchange
            and rule.board == item.board
            and rule.status == status
            and rule.effective_from <= on
            and (rule.effective_to is None or on <= rule.effective_to)
        ]
        if len(matches) != 1:
            raise ValueError("market rule not explicitly versioned for this date/state")
        return matches[0]
