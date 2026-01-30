import re

def parse_origin_options(value):
    if not value:
        return []

    return [
        opt.strip()
        for opt in value.split(",")
        if opt.strip()
    ]


def extract_sequence_and_year(code):
    """
    '000001-2025' -> (1, 2025)
    """
    try:
        seq_part, year_part = code.split("-")
        return int(seq_part), int(year_part)
    except Exception:
        return None, None