"""Shared pure helpers used across layers."""
from typing import Any


def merge_dict_list(dict_list: list[Any]) -> Any:
    """
    Recursively merges a list of dictionaries into a single dictionary.
    - Concatenates lists.
    - Recursively merges nested dictionaries.
    - Combines primitive values (deduplicates, joins strings with comma, etc.).
    """
    if not dict_list:
        return {}

    if not all(isinstance(x, dict) for x in dict_list):
        non_null = [x for x in dict_list if x is not None]
        if not non_null:
            return None
        seen = []
        for x in non_null:
            if x not in seen:
                seen.append(x)
        if len(seen) == 1:
            return seen[0]
        return seen

    merged = {}
    all_keys = set()
    for d in dict_list:
        all_keys.update(d.keys())

    for key in all_keys:
        values = [d[key] for d in dict_list if key in d]
        non_null_values = [v for v in values if v is not None]

        if not non_null_values:
            merged[key] = None
            continue

        if all(isinstance(v, list) for v in non_null_values):
            combined_list = []
            for lst in non_null_values:
                combined_list.extend(lst)
            merged[key] = combined_list
        elif all(isinstance(v, dict) for v in non_null_values):
            merged[key] = merge_dict_list(non_null_values)
        else:
            unique_vals = []
            for v in non_null_values:
                if v not in unique_vals:
                    unique_vals.append(v)

            if len(unique_vals) == 1:
                merged[key] = unique_vals[0]
            else:
                if all(isinstance(v, bool) for v in unique_vals):
                    merged[key] = any(unique_vals)
                else:
                    str_vals = [str(v) for v in unique_vals if str(v).strip()]
                    merged[key] = ", ".join(str_vals)

    return merged
