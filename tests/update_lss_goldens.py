"""Regenerate deterministic SurveyLoadResult snapshots for the checked-in LSS fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.survey_structure import survey_structure_from_lss


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"
GOLDEN_DIRECTORY = FIXTURE_DIRECTORY / "golden"


def main() -> None:
    GOLDEN_DIRECTORY.mkdir(exist_ok=True)
    for source_path in sorted(FIXTURE_DIRECTORY.glob("*.lss")):
        result = survey_structure_from_lss(source_path.read_bytes())
        target_path = (
            FIXTURE_DIRECTORY / "survey_load_result_783587.json"
            if source_path.stem == "limesurvey_survey_783587"
            else GOLDEN_DIRECTORY / f"{source_path.stem}.json"
        )
        target_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(target_path)


if __name__ == "__main__":
    main()
