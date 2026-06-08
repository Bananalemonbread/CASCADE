import json
import os
from datetime import datetime

from tqdm import tqdm

from cascade.analysis.Analysis import Analysis
from cascade.analysis.executor.Execution import Execution
from cascade.generation.Generation import Generation
from cascade.generation.test.MultiStepRustTestGenerator import is_public
from cascade.utils.RustUtils import (
    INJECTED_SUITE_PATH,
    build_replacement_test_dict_with_path,
    build_signature,
)
from cascade.utils.Utils import load_json_from_path, save_dicts_list_to_json


class RustTwoStepAnalysis(Analysis):
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
        no_original_tests=True,
    ):
        super().__init__(generator, executor)
        self.reexecute = reexecute or regenerate
        self.step_size = step_size
        self.regenerate = regenerate
        self.just_analyze = just_analyze
        self.debug = debug
        self.max_repair_tries = max_repair_tries
        self.no_original_tests = no_original_tests

    def analyze(self, data: list, input_path, output_path):
        def log(header, message):
            with open(os.path.join(output_path, "log.txt"), "a") as f:
                f.write(header + "\n")
                f.write(message + "\n")

        print(f"analyzing {len(data)} elements")

        analyzed_path = os.path.join(output_path, "analyzed.json")
        if os.path.exists(analyzed_path):
            data = load_json_from_path(analyzed_path)
            print(f"loaded existing analyzed data with {len(data)} elements")
        else:
            data = self.prepare_data(data)
            save_dicts_list_to_json(data, analyzed_path)

        if not self.just_analyze:
            print("setup executor rust image")
            self.executor.set_up(data, input_path, output_path)

            time_start = datetime.now()
            for idx, d in enumerate(data[::self.step_size]):
                try:
                    time_now = datetime.now()
                    time_elapsed = time_now - time_start
                    time_avg = time_elapsed / (idx + 1)
                    time_remaining = time_avg * (len(data) - (idx + 1))

                    print(
                        f"{time_now.strftime('%H:%M:%S')}  "
                        f"Analyzing function: {d['signature']['name']}. "
                        f"{idx + 1}/{len(data)}  "
                        f"Time so far: {str(time_elapsed).split('.')[0]} "
                        f"Estimated time remaining: {str(time_remaining).split('.')[0]}"
                    )

                    test_keyword = "new_tests" if is_public(d) else "new_tests_inject"
                    d.setdefault("results", {})

                    print("    Step 1 - New Tests")
                    if "new_tests" not in d or self.regenerate:
                        print("      generate new tests")
                        new_tests, chat_history = self.generator.generate_tests(d, input_path, output_path)

                        d["new_tests"] = new_tests
                        d["new_tests_history"] = chat_history

                        if new_tests == "":
                            log("GENERATION: no test could be generated.\nChatHistory:\n", str(chat_history))
                            d["verdict"] = "NoInco; error; step 1 (C +T'); ; ; "
                            continue
                    else:
                        print("      new tests already generated")

                    print("      execute new tests")
                    res1 = self.executor.execute("code", test_keyword, d, input_path, output_path)
                    log("Results after step 1", str(res1))

                    evaluated = self.evaluate(res1)
                    d["results"]["(code, new_tests)"] = list(res1)
                    amount_res = self.result_numbers(res1)

                    if evaluated == 0:
                        self.log_error(output_path, "S1 Error in tests", d, res1)
                        d["verdict"] = f"NoInco; error; step 1 (C +T'); {str(amount_res)}; ; "

                    elif evaluated == 1:
                        d["verdict"] = f"NoInco; pass; step 1 (C +T'); {str(amount_res)}; ; "

                    else:
                        print("    Step 2 - New Code")
                        if "new_code" not in d or self.regenerate:
                            print("      generate new code")
                            new_code, response = self.generator.generate_code(d, input_path, output_path)

                            d["new_code"] = new_code
                            d["new_code_response"] = response

                        print("      execute new code (with new tests)")
                        res2 = self.executor.execute("new_code", test_keyword, d, input_path, output_path)
                        log("Results after step 2", str(res2))

                        evaluated2 = self.evaluate(res2)
                        d["results"]["(new_code, new_tests)"] = list(res2)
                        amount_res2 = self.result_numbers(res2)

                        if evaluated2 == 0:
                            self.log_error(output_path, "S2 Error in generated code", d, res2)
                            d["verdict"] = f"NoInco; error; step 2 (C'+T'); {str(amount_res)}; {str(amount_res2)}"

                        else:
                            metric = self.calculate_metric(d["results"]["(code, new_tests)"], d["results"]["(new_code, new_tests)"])
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

                except Exception as e:
                    d["verdict"] = f"Error during analysis: {e}"
                    print(d["verdict"])

                if idx % 10 == 0:
                    self.save_results(data, output_path)

            time_total = str(datetime.now() - time_start).split(".")[0]
            print(f"Finished analysis in {time_total}")

            self.executor.tear_down(data)
            self.save_results(data, output_path)

        self.print_stats(data)

    def prepare_data(self, data):
        print("prepare data")
        for d in tqdm(data):
            if is_public(d):
                replacement_test_dict = build_replacement_test_dict_with_path(INJECTED_SUITE_PATH)
            else:
                replacement_test_dict = build_replacement_test_dict_with_path(d["code_file_path"])

            d["tests"] = [replacement_test_dict]

        return data

    def save_results(self, data, output_path):
        save_dicts_list_to_json(data, os.path.join(output_path, "analyzed.json"))
        save_dicts_list_to_json(
            [self.inconsistent_summary(item) for item in data if item.get("verdict", "").startswith("INCO")],
            os.path.join(output_path, "inconsistent_functions.json"),
        )

    def inconsistent_summary(self, item):
        result = item.get("results", {}).get("(new_code, new_tests)") or item.get("results", {}).get("(code, new_tests)") or [[], [], []]
        parent = item.get("parent", [])
        parent_name = parent[-1].get("name") if parent else None

        return {
            "id": item.get("id"),
            "file_name": os.path.basename(item.get("code_file_path", "")),
            "file_path": item.get("code_file_path"),
            "module_name": parent_name,
            "function_name": item.get("signature", {}).get("name"),
            "full_function_signature": build_signature(item, doc=False),
            "verdict": item.get("verdict"),
            "failed_testcases": list(result[1]),
            "errored_testcases": list(result[2]),
            "failing_testcases": list(result[1]) + list(result[2]),
        }

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

    def log_error(self, output_path, header, d, res):
        with open(os.path.join(output_path, "errors.txt"), "a") as f:
            f.write(header + "\n")
            f.write(str(res))
            f.write("\n------\nTests:\n")
            f.write(f"{d.get('new_tests', '')}\n")
            f.write("------\nCode:\n")
            f.write(d.get("code", ""))
            if "new_code" in d:
                f.write("\n------\nGenerated code:\n")
                f.write(d["new_code"])
            f.write("\n-----------------------\n")

    def result_numbers(self, res):
        return len(res[0]), len(res[1]), len(res[2])

    def evaluate(self, res):
        if res[0] == [] and res[1] == [] and res[2] == []:
            print("        Error")
            return 0
        elif res[1] == [] and res[2] == []:
            print("        Passed")
            return 1
        else:
            print("        Failed")
            return -1

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

            if parsed["step_info"] == "step 1 (C +T')":
                if parsed["test_result"] == "pass":
                    general_stats["Step1_passed"] += 1
                elif parsed["test_result"] == "error":
                    general_stats["Step1_error"] += 1

            elif parsed["step_info"] == "step 2 (C'+T')":
                general_stats["Step1_failed"] += 1

                if parsed["test_result"] == "pass":
                    general_stats["Step2_passed"] += 1
                elif parsed["test_result"] == "error":
                    general_stats["Step2_error"] += 1
                elif parsed["test_result"] == "fail":
                    general_stats["Step2_failed"] += 1

            if "metric" in d and len(d["metric"]["f2p"]) > 0:
                general_stats["Step2_f2p>0"] += 1

                if len(d["metric"]["p2f"]) == 0:
                    general_stats["incos"] += 1
                    incos.append(d)
                else:
                    general_stats["likely_incos"] += 1
                    likely_incos.append(d)

        print("incos:", len(incos))
        print("likely incos:", len(likely_incos))

        for key, value in general_stats.items():
            print(f"{key}: {value}")

        print("Incos:")
        for d in incos:
            print("--------------------------------------------------------")
            print(d["signature"]["name"])
            print("f2p testcases:", ", ".join(d["metric"]["f2p"]))
            print(build_signature(d, doc=True))
            print(d["code"])

    def parse_verdict(self, verdict: str):
        parts = verdict.split(";")
        return {
            "inco_status": parts[0].strip() if len(parts) > 0 else None,
            "test_result": parts[1].strip() if len(parts) > 1 else None,
            "step_info": parts[2].strip() if len(parts) > 2 else None,
            "step1_results": parts[3].strip() if len(parts) > 3 else None,
            "step2_results": parts[4].strip() if len(parts) > 4 else None,
            "metrics": parts[5].strip() if len(parts) > 5 else None,
        }
