import json
import os
from datetime import datetime

from cascade.analysis.Analysis import Analysis
from cascade.analysis.executor.Execution import Execution
from cascade.analysis.executor.ExecutionResults import ExecutionResults
from cascade.generation.Generation import Generation
from cascade.utils.PythonUtils import build_signature
from cascade.utils.Utils import load_json_from_path, save_dicts_list_to_json


class PythonTwoStepAnalysis(Analysis):
    def __init__(
        self,
        generator: Generation,
        executor: Execution,
        regenerate=False,
        reexecute=False,
        just_analyze=False,
        debug=0,
        step_size=1,
        max_repair_tries=3,
    ):
        super().__init__(generator, executor)
        self.reexecute = reexecute or regenerate
        self.step_size = step_size
        self.regenerate = regenerate
        self.just_analyze = just_analyze
        self.debug = debug
        self.max_repair_tries = max_repair_tries

    def analyze(self, data, input_path, output_path):
        def log(header, message):
            with open(os.path.join(output_path, "log.txt"), "a") as f:
                f.write(header + "\n")
                f.write(str(message) + "\n")

        analyzed_path = os.path.join(output_path, "analyzed.json")

        print(f"analyzing {len(data)} elements")
        if os.path.exists(analyzed_path):
            data = load_json_from_path(analyzed_path)
            print(f"loaded existing analyzed data with {len(data)} elements")
        else:
            data = self.prepare_data(data, input_path, output_path)
            save_dicts_list_to_json(data, analyzed_path)

        if not self.just_analyze:
            print("setup executor Python environment")
            self.executor.set_up(data, input_path, output_path)

            time_start = datetime.now()
            for idx, d in enumerate(data[::self.step_size]):
                try:
                    self.analyze_item(d, idx, len(data), time_start, input_path, output_path, log)
                except Exception as e:
                    d["verdict"] = f"Error during analysis: {e}"
                    log("Error during analysis", d["verdict"])

                if idx % 10 == 0:
                    self.save_results(data, output_path)

            time_total = str(datetime.now() - time_start).split(".")[0]
            print(f"Finished analysis in {time_total}")
            self.executor.tear_down(data)
            self.save_results(data, output_path)

        self.print_stats(data)

    def analyze_item(self, d, idx, total, time_start, input_path, output_path, log):
        time_now = datetime.now()
        time_elapsed = time_now - time_start
        time_avg = time_elapsed / (idx + 1)
        time_remaining = time_avg * (total - (idx + 1))

        print(
            f"{time_now.strftime('%H:%M:%S')}  "
            f"Analyzing function: {d['signature']['name']}. "
            f"{idx + 1}/{total}  "
            f"Time so far: {str(time_elapsed).split('.')[0]} "
            f"Estimated time remaining: {str(time_remaining).split('.')[0]}"
        )

        d.setdefault("results", {})

        print("    Step 1 - New Tests")
        if "new_tests" not in d or self.regenerate:
            print("      generate new tests")
            new_tests, chat_history = self.generator.generate_tests(d, input_path, output_path)
            d["new_tests"] = new_tests
            d["new_tests_history"] = chat_history

            if new_tests == "":
                log("GENERATION: no test could be generated.\nChatHistory:\n", chat_history)
                d["verdict"] = "NoInco; error; step 1 (C +T'); ; ; "
                return
        else:
            print("      new tests already generated")

        print("      execute new tests")
        exec_results: ExecutionResults = self.executor.execute("code", "new_tests", d, input_path, output_path)
        res1 = exec_results.results
        comp_errors = exec_results.comp_errors
        log("Results after step 1", exec_results)

        evaluated = self.evaluate(res1)
        d["repair_history"] = []

        for repair_index in range(self.max_repair_tries):
            if evaluated != 0 or not comp_errors:
                break

            print("      Try to generate repaired tests")
            repaired_tests, response_history = self.generator.repair_tests(
                d, input_path, output_path, comp_errors, "new_tests"
            )
            d["repair_history"].append(response_history)

            if repaired_tests == "":
                break

            old_tests_key = "tests_pre_repairstep_" + str(repair_index + 1)
            d[old_tests_key] = d["new_tests"]
            d["new_tests"] = repaired_tests

            print("      execute repaired tests")
            exec_results = self.executor.execute("code", "new_tests", d, input_path, output_path)
            res1 = exec_results.results
            comp_errors = exec_results.comp_errors
            log(f"Results after step 1-Repairstep Nr. {repair_index + 1}:", exec_results)

            d["repairsteps"] = repair_index + 1
            evaluated = self.evaluate(res1)

        amount_res = exec_results.results_numbers
        d["results"]["(code, new_tests)"] = res1

        if evaluated == 0:
            self.log_error(output_path, "S1 Error in tests", d, res1, comp_errors)
            d["verdict"] = f"NoInco; error; step 1 (C +T'); {str(amount_res)}; ; "
            print(d["verdict"])
            return

        if evaluated == 1:
            d["verdict"] = f"NoInco; pass; step 1 (C +T'); {str(amount_res)}; ; "
            print(d["verdict"])
            return

        print("    Step 2 - New Code")
        if "new_code" not in d or self.regenerate:
            print("      generate new code")
            new_code, response = self.generator.generate_code(d, input_path, output_path)
            d["new_code"] = new_code
            d["new_code_response"] = response

        print("      execute new code (with new tests)")
        exec_results = self.executor.execute("new_code", "new_tests", d, input_path, output_path)
        res2 = exec_results.results
        comp_errors = exec_results.comp_errors
        log("Results after step 2", exec_results)

        evaluated2 = self.evaluate(res2)
        amount_res2 = exec_results.results_numbers
        d["results"]["(new_code, new_tests)"] = res2

        if evaluated2 == 0:
            self.log_error(output_path, "S2 Error in code?", d, res2, comp_errors)
            d["verdict"] = f"NoInco; error; step 2 (C'+T'); {str(amount_res)}; {str(amount_res2)}"
            print(d["verdict"])
            return

        metric = self.calculate_metric(res1, res2)
        d["metric"] = metric
        metric_lengths = ", ".join(f"{k}: {len(v)}" for k, v in metric.items())

        if evaluated2 == 1:
            d["verdict"] = "INCO; pass; step 2 (C'+T');"
        elif len(metric["f2p"]) > 0 and len(metric["p2f"]) == 0:
            d["verdict"] = "INCO; fail; step 2 (C'+T');"
        else:
            d["verdict"] = "NoInco; fail; step 2 (C'+T');"

        d["verdict"] += f" {str(amount_res)}; {str(amount_res2)}; {metric_lengths}"
        print(d["verdict"])

    def calculate_metric(self, res1, res2):
        r1 = [res1[0], res1[1] + res1[2]]
        r2 = [res2[0], res2[1] + res2[2]]
        metric = {"p2p": [], "f2f": [], "p2f": [], "f2p": []}

        for test_name in r1[0]:
            if test_name in r2[0]:
                metric["p2p"].append(test_name)
            elif test_name in r2[1]:
                metric["p2f"].append(test_name)

        for test_name in r1[1]:
            if test_name in r2[0]:
                metric["f2p"].append(test_name)
            elif test_name in r2[1]:
                metric["f2f"].append(test_name)

        return metric

    def evaluate(self, res):
        if res[2]:
            print("        Error")
            return 0
        if res[0] == [] and res[1] == [] and res[2] == []:
            print("        Error")
            return 0
        if res[1] == [] and res[2] == []:
            print("        Passed")
            return 1

        print("        Failed")
        return -1

    def prepare_data(self, data, input_path, output_path):
        print("prepare Python data")
        for d in data:
            d.setdefault("tests", [])
            d.setdefault("test_imports", [])
            d.setdefault("test_file_path", self.default_test_file_path(d))
        return data

    def default_test_file_path(self, d):
        code_file_path = d["code_file_path"]
        directory = os.path.dirname(code_file_path)
        filename = os.path.basename(code_file_path)
        return os.path.join(directory, "test_" + filename)

    def log_error(self, output_path, header, d, result, comp_errors):
        with open(os.path.join(output_path, "errors.txt"), "a") as f:
            f.write(header + "\n")
            f.write(str(result))
            f.write("\n------\nTests:\n")
            f.write(f"{d.get('new_tests', '')}\n")
            f.write("------\nCode:\n")
            f.write(d.get("code", ""))
            if comp_errors:
                f.write("\n------\nErrors:\n")
                f.write(comp_errors)
            else:
                f.write("\n-------\nNo captured errors. Check log.\n")
            f.write("-----------------------\n")

    def save_results(self, data, output_path):
        save_dicts_list_to_json(data, os.path.join(output_path, "analyzed.json"))
        save_dicts_list_to_json(
            [self.build_inco_summary(item) for item in data if item.get("verdict", "").startswith("INCO")],
            os.path.join(output_path, "inconsistent_functions.json"),
        )

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
            "class_name": self.get_class_name(item),
            "function_name": item.get("signature", {}).get("name"),
            "full_function_signature": build_signature(item, doc=False),
            "verdict": item.get("verdict"),
            "failed_testcases": list(result[1]),
            "errored_testcases": list(result[2]),
            "failing_testcases": list(result[1]) + list(result[2]),
        }

    def get_class_name(self, item):
        parents = item.get("parent", [])
        if isinstance(parents, dict):
            parents = [parents]

        for parent in reversed(parents):
            if parent.get("parent_type") == "Class":
                return parent.get("name")

        return None

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

    def parse_verdict(self, verdict):
        parts = verdict.split(";")
        return {
            "inco_status": parts[0].strip() if len(parts) > 0 else None,
            "test_result": parts[1].strip() if len(parts) > 1 else None,
            "step_info": parts[2].strip() if len(parts) > 2 else None,
            "step1_results": parts[3].strip() if len(parts) > 3 else None,
            "step2_results": parts[4].strip() if len(parts) > 4 else None,
            "metrics": parts[5].strip() if len(parts) > 5 else None,
        }

    def update_repair_stats(self, d, parsed, repair_stats):
        if "repairsteps" not in d:
            for index in range(self.max_repair_tries, 0, -1):
                if f"tests_pre_repairstep_{index}" in d:
                    d["repairsteps"] = index
                    break

        if "repairsteps" not in d:
            return

        rep_steps = d["repairsteps"]
        repair_stats["total_repair_steps"] += rep_steps
        repair_stats["total_attempted_repairs"] += 1

        if rep_steps == 1:
            repair_stats["successful_after_first_try"] += 1
            repair_stats["successful_repairs"] += 1
        elif rep_steps == 2:
            repair_stats["successful_after_second_try"] += 1
            repair_stats["successful_repairs"] += 1
        elif rep_steps >= 3:
            if parsed["step_info"] == "step 2 (C +T')" or (
                parsed["step_info"] == "step 1 (C +T')" and parsed["test_result"] == "pass"
            ):
                repair_stats["successful_after_third_try"] += 1
                repair_stats["successful_repairs"] += 1
            else:
                repair_stats["failed_repairs"] += 1

    def update_general_stats(self, d, parsed, general_stats, repair_stats, incos, likely_incos):
        if parsed["step_info"] == "step 1 (C +T')":
            if parsed["test_result"] == "pass":
                general_stats["Step1_passed"] += 1
            elif parsed["test_result"] == "error":
                general_stats["Step1_error"] += 1
            return

        if parsed["step_info"] == "step 2 (C'+T')":
            general_stats["Step1_failed"] += 1
            if parsed["test_result"] == "pass":
                general_stats["Step2_passed"] += 1
            elif parsed["test_result"] == "error":
                general_stats["Step2_error"] += 1
                repair_stats["code_errors"] += 1
            elif parsed["test_result"] == "fail":
                general_stats["Step2_failed"] += 1

        if parsed["inco_status"] == "INCO":
            general_stats["incos"] += 1
            incos.append(d)
            if "metric" in d and len(d["metric"]["f2p"]) > 0:
                general_stats["Step2_f2p>0"] += 1
            return

        if "metric" in d and len(d["metric"]["f2p"]) > 0:
            general_stats["Step2_f2p>0"] += 1
            if len(d["metric"]["p2f"]) == 0:
                general_stats["incos"] += 1
                incos.append(d)
            else:
                general_stats["likely_incos"] += 1
                likely_incos.append(d)
