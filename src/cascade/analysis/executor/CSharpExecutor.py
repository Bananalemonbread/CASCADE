import shutil
import tempfile
import json
import os

from cascade.analysis.executor.AnalysisExecutor import AnalysisExecutor, succeeded, failed, errored
from cascade.analysis.executor.builders.CSharpBuilder import CSharpBuilder
from cascade.utils.DockerizedWrapper import DockerizedWrapper
from cascade.utils.CSharpUtils import run_modification
from pathlib import Path

class CSharpExecutor(AnalysisExecutor):
    def __init__(self, debug=False, builder=None):
        super().__init__()
        self.debug = debug
        self.test_report_filename = "$HOME/test_result.trx"
        self.builder = CSharpBuilder(image="mcr.microsoft.com/dotnet/sdk:8.0",
                                     new_image_name="dotnet8.0",
                                     dotnet_args=f"--filter %t --logger \"trx;LogFileName={self.test_report_filename}\"",
                                     set_up_command="build",
                                     set_up_args="--property WarningLevel=0")

    def execute(self, code: str, tests: str, context: dict, input_path, output_path: str) -> (succeeded, failed, errored):
        # because the input_path points to the .sln file of the project
        input_path = os.path.dirname(input_path)
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                shutil.copytree(input_path, temp_dir, dirs_exist_ok=True)
            except Exception as e:
                print("could not copy root path")
                print(e)

            entry = os.path.join(temp_dir, "entry.json")
            with open(entry, "w") as json_entry:
                json.dump(context, json_entry)

            run_modification(temp_dir, entry, code, tests)

            os.remove(entry)

            dock_ex = DockerizedWrapper(debug=self.debug)

            test = context["tests"][0] #TODO: think about handling multiple tests?
            test_class_name = Path(test['test_file_path']).stem
            fully_qualified_name = test["test_namespace"] + "." + test_class_name
            run_test_class_command = self.builder.test_pattern.replace('%t', fully_qualified_name)

            dock_context = {
                "image": self.builder.image,
                "directory": temp_dir,
                "command": f"pwd; ls; cat -n {context['code_file_path']}; cat -n {test['test_file_path']};"
                           f"{run_test_class_command}", #TODO: the cat commands are not working at the moment
                "eval_command": f"cat {self.test_report_filename}",
                "eval_function": self.builder.eval_function
            }

            # TODO: why is one container started in here and killed after eval ...
            result = dock_ex.execute(dock_context, output_path)

        return result

    #TODO: ... while one is setup and running in here for the whole duration?
    def set_up(self, data, input_path, output_path):
        # because the input_path points to the .sln file of the project
        input_path = os.path.dirname(input_path)

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