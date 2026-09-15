"""Report native mappings and synthetic checks that actually passed.

Run from the adapter root. This is not a claim of live LimeSurvey, CSV or renderer
coverage. Real-file regressions and complete consumer tests remain separate.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.survey_structure.field_normalizer import QUESTION_TYPES

MAPPING_TESTS = (
    "test_each_supported_native_type_has_an_explicit_semantic_mapping",
    "test_matrix_axes_and_separate_scales",
)
CHECKS = (
    f"tests/test_survey_structure.py::{MAPPING_TESTS[0]}",
    "tests/test_advanced_matrices.py",
    "tests/test_condition_parser.py",
    "tests/test_survey_structure.py::test_builder_normalizes_internal_child_aliases_and_type_specific_validation",
    "tests/test_survey_structure.py::test_relevant_limesurvey_attributes_are_normalized_or_retained_explicitly",
    "tests/test_survey_structure.py::test_dynamic_selection_limit_is_reported_without_inventing_a_number",
    "tests/test_survey_structure.py::test_unknown_condition_reference_becomes_an_import_warning",
    "tests/test_survey_structure.py::test_builder_keeps_group_and_question_visibility_as_separate_neutral_rules",
)


def main():
    with tempfile.TemporaryDirectory(prefix="ls-compatibility-") as directory:
        junit = Path(directory) / "tests.xml"
        result = subprocess.run([
            sys.executable, "-m", "pytest", "-q",
            *CHECKS,
            f"--junitxml={junit}",
        ], cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            sys.stderr.write(result.stdout + result.stderr)
            raise SystemExit(result.returncode)
        tests = ET.parse(junit).findall(".//testcase")
        verified = {case.attrib["name"].split("[")[1].split("-")[0]
                    for case in tests if case.attrib["name"].split("[")[0] in MAPPING_TESTS}
        if any(list(case) for case in tests) or verified != set(QUESTION_TYPES):
            raise SystemExit("Native mapping table and passing, non-skipped tests differ")
        print(json.dumps({"evidence": "synthetic-normalization", "liveIntegration": False,
            "mappings": [{"nativeType": code, "fieldType": QUESTION_TYPES[code]}
                         for code in sorted(verified)],
            "checks": [{"test": f'{case.attrib["classname"]}::{case.attrib["name"]}',
                        "status": "passed"} for case in tests]}, indent=2))


if __name__ == "__main__":
    main()
