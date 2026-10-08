import math


# All prices in rupees.
PRICES = {
    # Single-sided: price per printed page
    "single": {"bw": 2, "color": 5},

    # Double-sided: price per sheet (two pages)
    "double": {"bw": 3, "color": 8},

    # Extra charge per sheet for large paper
    "paper_extra": {"a4": 0, "letter": 0, "a3": 2},
}

COLORS = ("bw", "color")
PAPERS = ("a4", "a3", "letter")
SIDES = ("single", "double")


def sheets_needed(pages, sides):
    if sides == "double":
        return math.ceil(pages / 2)
    return pages


def calculate_price(pages, color, copies, paper, sides):
    if color not in COLORS:
        raise ValueError(f"Unknown colour option: {color}")
    if paper not in PAPERS:
        raise ValueError(f"Unknown paper size: {paper}")
    if sides not in SIDES:
        raise ValueError(f"Unknown sides option: {sides}")
    if pages < 1 or copies < 1:
        raise ValueError("Pages and copies must be at least 1")

    sheets = sheets_needed(pages, sides)
    rate = PRICES[sides][color] + PRICES["paper_extra"][paper]
    total = sheets * rate * copies

    return {
        "pages": pages,
        "sheets": sheets,
        "copies": copies,
        "rate_per_sheet": rate,
        "total": total,
    }
