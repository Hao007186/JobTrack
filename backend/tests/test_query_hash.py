from datetime import timedelta

from tests.watches.conftest import TODAY, conditions


def test_same_conditions_same_hash() -> None:
    assert conditions().query_hash() == conditions().query_hash()


def test_airline_order_irrelevant() -> None:
    assert (
        conditions(airlines=("CI", "BR")).query_hash()
        == conditions(airlines=("BR", "CI")).query_hash()
    )


def test_adults_changes_hash() -> None:
    assert conditions(adults=2).query_hash() != conditions().query_hash()


def test_is_demo_changes_hash() -> None:
    assert conditions(is_demo=True).query_hash() != conditions().query_hash()


def test_return_date_changes_hash() -> None:
    round_trip = conditions(return_date=TODAY + timedelta(days=35))
    assert round_trip.query_hash() != conditions().query_hash()


def test_hash_is_sha256_hex() -> None:
    h = conditions().query_hash()
    assert len(h) == 64
    int(h, 16)
