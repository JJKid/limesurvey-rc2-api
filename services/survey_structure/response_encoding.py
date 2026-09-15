"""Declare native selection storage before neutral consumers receive a field."""
from typing import Mapping


def selection_encoding(selected: str, unselected: str, labels: Mapping[str, str]) -> dict[str, str]:
    """Keep stored values separate from localized labels; missing is not unselected."""
    return {"selectedValue": selected, "unselectedValue": unselected,
            "selectedLabel": labels["yes"], "unselectedLabel": labels["no"]}
