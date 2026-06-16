import os

from cascade.analysis.PythonTwoStepAnalysis import PythonTwoStepAnalysis
from cascade.utils.CSharpUtils import build_signature, class_name_from_path, parent_context
from cascade.utils.Utils import save_dicts_list_to_json


class CSharpTwoStepAnalysis(PythonTwoStepAnalysis):
    def prepare_data(self, data, input_path, output_path):
        print("prepare C# data")
        for d in data:
            d.setdefault("tests", [])
            if not d["tests"]:
                d["tests"] = [self.default_test_metadata(d)]

            test = d["tests"][0]
            d.setdefault("test_file_path", test.get("test_file_path") or self.default_test_file_path(d))
            test.setdefault("test_file_path", d["test_file_path"])
            test.setdefault("test_class_name", class_name_from_path(d["test_file_path"]))
            test.setdefault("test_namespace", self.default_test_namespace(d))
            test.setdefault("test_runner", "xUnit")
            test.setdefault("test_imports", d.get("test_imports", []))
            test.setdefault("project_path", self.default_test_project_path(input_path))

        return data

    def default_test_metadata(self, d):
        test_file_path = self.default_test_file_path(d)
        return {
            "test_file_path": test_file_path,
            "test_class_name": class_name_from_path(test_file_path),
            "test_namespace": self.default_test_namespace(d),
            "test_runner": "xUnit",
            "test_imports": ["using Xunit;"],
        }

    def default_test_file_path(self, d):
        code_file_path = d["code_file_path"]
        directory = os.path.dirname(code_file_path)
        filename = os.path.splitext(os.path.basename(code_file_path))[0]
        return os.path.join(directory, f"{filename}Test.cs")

    def default_test_namespace(self, d):
        namespace = parent_context(d).get("namespace")
        return f"{namespace}.Tests" if namespace else "Cascade.GeneratedTests"

    def default_test_project_path(self, input_path):
        if os.path.isfile(input_path):
            return os.path.basename(input_path)
        return "."

    def build_inco_summary(self, item):
        result = (
            item.get("results", {}).get("(new_code, new_tests)")
            or item.get("results", {}).get("(code, new_tests)")
            or [[], [], []]
        )
        return {
            "id": item.get("id"),
            "file_name": os.path.basename(item.get("code_file_path", "")),
            "file_path": item.get("code_file_path"),
            "class_name": parent_context(item).get("name"),
            "function_name": item.get("signature", {}).get("name"),
            "full_function_signature": build_signature(item, doc=False),
            "verdict": item.get("verdict"),
            "failed_testcases": list(result[1]),
            "errored_testcases": list(result[2]),
            "failing_testcases": list(result[1]) + list(result[2]),
        }

    def save_results(self, data, output_path):
        save_dicts_list_to_json(data, os.path.join(output_path, "analyzed.json"))
        save_dicts_list_to_json(
            [self.build_inco_summary(item) for item in data if item.get("verdict", "").startswith("INCO")],
            os.path.join(output_path, "inconsistent_functions.json"),
        )

    def print_stats(self, data):
        general_stats = {
            "complete_errors": 0,
            "Step1_passed": 0,
            "Step1_error": 0,
            "Step1_failed": 0,
            "Step2_error": 0,
            "Step2_failed": 0,
            "Step2_passed": 0,
            "Step2_f2p>0": 0,
            "incos": 0,
            "likely_incos": 0,
        }
        repair_stats = {
            "total_repair_steps": 0,
            "total_attempted_repairs": 0,
            "successful_repairs": 0,
            "successful_after_first_try": 0,
            "successful_after_second_try": 0,
            "successful_after_third_try": 0,
            "failed_repairs": 0,
            "code_errors": 0,
        }
        incos = []
        likely_incos = []

        for d in data:
            verdict = d.get("verdict")
            if not verdict:
                print(d["signature"]["name"], "\t", "No verdict")
                continue
            if ";" not in verdict:
                general_stats["complete_errors"] += 1
                continue

            parsed = self.parse_verdict(verdict)
            print(d["signature"]["name"], "\t", verdict)
            self.update_repair_stats(d, parsed, repair_stats)
            self.update_general_stats(d, parsed, general_stats, repair_stats, incos, likely_incos)

        print("incos:", len(incos))
        print("likely incos:", len(likely_incos))

        for key, value in general_stats.items():
            print(f"{key}: {value}")
        for key, value in repair_stats.items():
            print(f"{key}: {value}")

        print("Incos:")
        for d in incos:
            print("--------------------------------------------------------")
            print(d["signature"]["name"])
            print("f2p testcases: ", ", ".join(d["metric"]["f2p"]))
            print(build_signature(d, doc=True))
            print(d["code"])
