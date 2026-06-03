import shutil
import tempfile
import json
import os

from cascade.analysis.executor.AnalysisExecutor import AnalysisExecutor
from cascade.analysis.executor.builders.RustBuilder import RustBuilder
from cascade.generation.test.MultiStepRustTestGenerator import is_public
from cascade.utils.DockerizedWrapper import DockerizedWrapper
from cascade.utils.RustUtils import run_modification, INJECTED_SUITE_NAME, INJECTED_MODULE_NAME

class RustExecutor(AnalysisExecutor):
    def __init__(self, debug=False, image="rust:latest", rust_args="--no-fail-fast", timeout=120):
        super().__init__()
        self.debug = debug
        self.builder = RustBuilder(image=image,
                                     new_image_name=f"rust-pre-compiled-project",
                                     set_up_command="cargo fetch; cargo build --tests",
                                     set_up_args="")

        self.pattern = f"echo \"[INFO] Tests run starting!\" > output;export RUSTFLAGS=\"-Awarnings\"; timeout {timeout} cargo build --tests; timeout {timeout} cargo test %placeholder {rust_args} > output 2>&1; cat output"

    def execute(self, code: str, tests: str, context: dict, input_path, output_path: str):

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                shutil.copytree(input_path, temp_dir, dirs_exist_ok=True)
            except Exception as e:
                print("could not copy root path")
                print(e)

            entry = os.path.join(temp_dir, "entry.json")
            with open(entry, "w") as json_entry:
                json.dump(context, json_entry)

            process = run_modification(temp_dir, entry, code, tests)

            with open(os.path.join(output_path, "log.txt"), "a") as file:
                file.write("Modifying context with id: " + str(context["id"]) + "\n")
                file.write(process.stdout + "\n")
                file.write(process.stderr + "\n")

            if process.stderr:
                if self.debug:
                    print(process.stdout)
                    print(process.stderr)
                return [], [], []

            os.remove(entry)

            dock_ex = DockerizedWrapper(debug=self.debug)

            # THIS IS JUST FOR THE EXPERIMENT RUN
            test = context["tests"][0] #we can be sure that it exists

            if is_public(context):
                command = "--test " + INJECTED_SUITE_NAME
            else:
                command = INJECTED_MODULE_NAME

            run_test_command = self.pattern.replace("%placeholder", command)

            dock_context = {
                "image": self.builder.new_image_name,
                "directory": temp_dir,
                "command": #f"pwd; ls; cat -n {context['code_file_path']}; cat -n {test['test_file_path']};"
                           f"cat -n {test['test_file_path']}; {run_test_command}",
                "eval_command": f"cat output",
                "eval_function": self.builder.eval_function
            }

            result = dock_ex.execute(dock_context, output_path)

        return result

    def set_up(self, data, input_path, output_path):
        """
        This setup method is only used to check if the project can be built.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                shutil.copytree(input_path, temp_dir, dirs_exist_ok=True)

            except Exception as e:
                print("could not copy root path")
                print(e)

            if self.builder:
                return self.builder.set_up(temp_dir, None, output_path)
        return False

    def tear_down(self, context):
        if self.builder:
            self.builder.tear_down(context[0])
