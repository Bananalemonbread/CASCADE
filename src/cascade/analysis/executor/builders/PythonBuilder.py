import re

from cascade.analysis.executor.ExecutionResults import ExecutionResults
from cascade.analysis.executor.builders.Builder import Builder


class PythonBuilder(Builder):
    def __init__(self, image="python:3.12", timeout=120):
        test_pattern = (
            "python -m pip install pytest >/tmp/pytest-install.log 2>&1; "
            f"timeout {timeout} python -m pytest -q %t --tb=short > output 2>&1; "
            "status=$?; cat output > out; echo \"[PYTEST_EXIT_CODE] $status\" >> out; cat output"
        )
        super().__init__(
            test_pattern=test_pattern,
            eval_function=self.eval_function,
            image=image,
        )

    def eval_function(self, output):
        results = ExecutionResults()
        results.parsed_file = output

        passed = re.findall(r"^PASSED\s+(.+)$", output, flags=re.MULTILINE)
        failed = re.findall(r"^FAILED\s+(.+?)(?:\s+-.*)?$", output, flags=re.MULTILINE)
        errored = re.findall(r"^ERROR\s+(.+?)(?:\s+-.*)?$", output, flags=re.MULTILINE)

        short_summary = re.search(r"=+ short test summary info =+\n(?P<summary>.*?)(?:\n=+|$)", output, flags=re.DOTALL)
        if short_summary:
            for line in short_summary.group("summary").splitlines():
                match = re.match(r"(FAILED|ERROR)\s+(.+?)(?:\s+-.*)?$", line.strip())
                if not match:
                    continue
                outcome, test_name = match.groups()
                if outcome == "FAILED" and test_name not in failed:
                    failed.append(test_name)
                elif outcome == "ERROR" and test_name not in errored:
                    errored.append(test_name)

        if not passed:
            passed_count = self.extract_count(output, "passed")
            known_non_passed = len(set(failed)) + len(set(errored))
            passed = [f"passed_{index + 1}" for index in range(max(0, passed_count - known_non_passed))]

        failed = list(dict.fromkeys(failed))
        errored = list(dict.fromkeys(errored))
        passed = list(dict.fromkeys(passed))

        results.results = (passed, failed, errored)
        results.results_numbers = (len(passed), len(failed), len(errored))
        results.test_overview_matches = re.findall(
            r"=+ .*?(?:passed|failed|error).*? in .*? =+",
            output,
        )

        exit_code = self.extract_exit_code(output)
        if self.has_collection_or_import_error(output) or (
            exit_code not in (None, 0) and not any(results.results)
        ):
            results.comp_errors = output
            results.comp_error_matches = self.extract_error_sections(output)
            if not any(results.results):
                results.results = ([], [], [f"pytest_exit_code_{exit_code}"])
                results.results_numbers = (0, 0, 1)

        return results

    def extract_count(self, output, label):
        matches = re.findall(rf"(\d+)\s+{label}", output)
        return int(matches[-1]) if matches else 0

    def has_collection_or_import_error(self, output):
        return (
            "ImportError" in output
            or "ModuleNotFoundError" in output
            or "SyntaxError" in output
            or "ERROR collecting" in output
            or "Interrupted:" in output
            or "No module named pytest" in output
        )

    def extract_error_sections(self, output):
        sections = re.findall(r"_{2,} ERROR collecting .*?(?=\n_{2,}|\n=+|$)", output, flags=re.DOTALL)
        if sections:
            return sections
        matches = re.findall(r"(?:ImportError|ModuleNotFoundError|SyntaxError):.*", output)
        return matches or ([output] if output else [])

    def extract_exit_code(self, output):
        match = re.search(r"\[PYTEST_EXIT_CODE\]\s+(\d+)", output)
        return int(match.group(1)) if match else None

    def tear_down(self, context):
        pass
