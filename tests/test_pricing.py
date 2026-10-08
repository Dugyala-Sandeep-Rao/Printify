import pytest

from pricing import calculate_price


def test_single_sided_black_and_white():
    assert calculate_price(10, "bw", 1, "a4", "single")["total"] == 20


def test_single_sided_colour_with_copies():
    assert calculate_price(4, "color", 3, "a4", "single")["total"] == 60


def test_double_sided_rounds_up_to_whole_sheets():
    quote = calculate_price(5, "bw", 1, "a4", "double")
    assert quote["sheets"] == 3
    assert quote["total"] == 9


def test_double_sided_colour_is_cheaper_than_single_sided():
    single = calculate_price(10, "color", 1, "a4", "single")["total"]
    double = calculate_price(10, "color", 1, "a4", "double")["total"]
    assert double < single


def test_a3_adds_extra_per_sheet():
    assert calculate_price(2, "bw", 1, "a3", "single")["total"] == 8
    assert calculate_price(2, "bw", 1, "a3", "double")["total"] == 5


@pytest.mark.parametrize(
    "args",
    [
        (0, "bw", 1, "a4", "single"),
        (1, "bw", 0, "a4", "single"),
        (1, "rainbow", 1, "a4", "single"),
        (1, "bw", 1, "a5", "single"),
        (1, "bw", 1, "a4", "triple"),
    ],
)
def test_invalid_options_are_rejected(args):
    with pytest.raises(ValueError):
        calculate_price(*args)
