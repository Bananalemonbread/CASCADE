import json
import os
import shutil
import tempfile
import uuid

from cascade.analysis.executor.AnalysisExecutor import AnalysisExecutor
from cascade.analysis.executor.ExecutionResults import ExecutionResults
from cascade.analysis.executor.builders.CSharpBuilder import CSharpBuilder
from cascade.utils.CSharpUtils import run_modification
from cascade.utils.DockerizedWrapper import DockerizedWrapper

class CSharpExecutor(AnalysisExecutor):
    def __init__(
                 self,
                 debug=False,
                 dotnet_args="",
                 set_up_dotnet_command="build",
                 set_up_dotnet_args="",
                 image="mcr.microsoft.com/dotnet/sdk:8.0",
                 framework="net9.0"
                ):
        
        super().__init__()
        self.debug = debug
        self.test_report_filename = "$HOME/test_result.trx"

        image_name_id = str(uuid.uuid4())

        standard_dotnet_args = (
            f"--framework {framework} "
            "/p:EnableWindowsTargeting=true "
            f"--logger \"trx;LogFileName={self.test_report_filename}\""
        )

        if dotnet_args == "":
            dotnet_args = standard_dotnet_args

        if set_up_dotnet_args == "":
            set_up_dotnet_args = (
                "--verbosity quiet "
                "/p:WarningLevel=0 "
                "/p:EnableWindowsTargeting=true"
            )

        self.builder = CSharpBuilder(
            image=image,
            new_image_name=image_name_id,
            dotnet_args=dotnet_args,
            set_up_command=f"dotnet {set_up_dotnet_command}",
            set_up_args=set_up_dotnet_args,
            timeout=300,
        )

    def execute(self, code: str, tests: str, context: dict, input_path, output_path: str):
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

            test = context["tests"][0] #TODO: think about handling multiple tests?
            test_class_name = test['test_class_name']
            test_project_path = test['project_path']
            fully_qualified_name = test["test_namespace"] + "." + test_class_name
            run_test_class_command =  self.builder.test_pattern.replace('%p', test_project_path).replace('%t', fully_qualified_name)

            dock_context = {
                "image": self.builder.image,
                "directory": temp_dir,
                "command": #f"pwd; ls; cat -n {context['code_file_path']}; cat -n {test['test_file_path']};"
                           f"cat -n {test['test_file_path']}; {run_test_class_command}",
                "eval_command": f"cat {self.test_report_filename}",
                "eval_function": self.builder.eval_function
            }


            result = dock_ex.execute(dock_context, output_path)

        return result

    def set_up(self, data, input_path, output_path):
        """
        This setup method is only used to check if the project can be built.
        """
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
