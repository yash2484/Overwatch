from datetime import date

import pytest

from overwatch.imagery.search_windows import candidate_windows


def test_default_yields_original_plus_four_widened() -> None:
    wins = candidate_windows(date(2021, 1, 1), date(2021, 1, 31))
    assert wins == [
        (date(2021, 1, 1), date(2021, 1, 31)),
        (date(2021, 1, 1), date(2021, 2, 15)),
        (date(2021, 1, 1), date(2021, 3, 2)),
        (date(2021, 1, 1), date(2021, 3, 17)),
        (date(2021, 1, 1), date(2021, 4, 1)),
    ]


def test_custom_step_and_cap() -> None:
    wins = candidate_windows(date(2021, 1, 1), date(2021, 1, 10), step_days=10, cap_days=20)
    assert [w[1] for w in wins] == [date(2021, 1, 10), date(2021, 1, 20), date(2021, 1, 30)]


def test_end_before_start_raises() -> None:
    with pytest.raises(ValueError, match="before start"):
        candidate_windows(date(2021, 2, 1), date(2021, 1, 1))
