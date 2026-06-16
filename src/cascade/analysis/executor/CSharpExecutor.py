import json
import os
import shutil
import tempfile
import uuid

from cascade.analysis.executor.AnalysisExecutor import AnalysisExecutor
from cascade.analysis.executor.ExecutionResults import ExecutionResults
from cascade.analysis.executor.builders.CSharpBuilder import CSharpBuilder
from cascade.utils.CSharpUtils import run_modification, resolve_tool_path
from cascade.utils.DockerizedWrapper import DockerizedWrapper


class CSharpExecutor(AnalysisExecutor):
    def __init__(
        self,
        debug=False,
        dotnet_args="",
        set_up_dotnet_command="build",
        set_up_dotnet_args="",
        image="mcr.microsoft.com/dotnet/sdk:9.0",
        framework="net9.0",
        tool_path=None,
        timeout=300,
    ):
        super().__init__()
        self.debug = debug
        self.framework = framework
        self.tool_path = resolve_tool_path(tool_path, require_exists=False)
        self.test_report_filename = "$HOME/test_result.trx"

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
            new_image_name=f"csharp-pre-compiled-project-{uuid.uuid4()}",
            dotnet_args=dotnet_args,
            set_up_command=f"dotnet {set_up_dotnet_command}",
            set_up_args=set_up_dotnet_args,
            timeout=timeout,
        )

    def execute(self, code: str, tests: str, context: dict, input_path, output_path: str):
        project_root = self.project_root(input_path)
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                shutil.copytree(project_root, temp_dir, dirs_exist_ok=True)
            except Exception as e:
                return self.build_execution_results(([], [], ["copy_project"]), comp_errors=str(e))

            entry = os.path.join(temp_dir, "entry.json")
            with open(entry, "w", encoding="utf-8") as json_entry:
                json.dump(context, json_entry)

            try:
                process = run_modification(temp_dir, entry, code, tests, tool_path=self.tool_path)
            except Exception as e:
                return self.build_execution_results(([], [], ["modify_project"]), comp_errors=str(e))
            finally:
                if os.path.exists(entry):
                    os.remove(entry)

            self.log_modification(output_path, context, process)
            if process.returncode != 0 or process.stderr:
                comp_errors = (process.stdout + "\n" + process.stderr).strip()
                if self.debug:
                    print(comp_errors)
                return self.build_execution_results(([], [], ["modify_project"]), comp_errors=comp_errors)

            test = (context.get("tests") or [{}])[0]
            test_file_path = test.get("test_file_path") or context.get("test_file_path", "")
            test_project_path = self.normalize_project_path(
                test.get("project_path") or self.test_project_path(input_path),
                project_root,
            )
            fully_qualified_name = self.test_filter_name(test, test_file_path)

            run_test_class_command = (
                self.builder.test_pattern
                .replace("%p", self.shell_quote(test_project_path))
                .replace("%t", fully_qualified_name.replace('"', '\\"'))
            )

            dock_context = {
                "image": self.builder.image,
                "directory": temp_dir,
                "command": (
                    f"cat -n {self.shell_quote(context.get('code_file_path', ''))}; "
                    f"cat -n {self.shell_quote(test_file_path)}; "
                    f"{run_test_class_command}"
                ),
                "eval_command": f"cat {self.test_report_filename} 2>/dev/null || cat out",
                "eval_function": self.builder.eval_function,
            }

            result = DockerizedWrapper(debug=self.debug).execute(dock_context, output_path)

        return result

    def set_up(self, data, input_path, output_path):
        project_root = self.project_root(input_path)
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                shutil.copytree(project_root, temp_dir, dirs_exist_ok=True)
            except Exception as e:
                print("could not copy root path")
                print(e)
                return False

            if self.builder:
                return self.builder.set_up(temp_dir, None, output_path)
        return False

    def tear_down(self, context):
        if self.builder:
            self.builder.tear_down(context)

    def project_root(self, input_path):
        return os.path.dirname(input_path) if os.path.isfile(input_path) else input_path

    def test_project_path(self, input_path):
        return os.path.basename(input_path) if os.path.isfile(input_path) else "."

    def normalize_project_path(self, project_path, project_root):
        if not project_path:
            return "."
        if os.path.isabs(project_path):
            try:
                return os.path.relpath(project_path, project_root)
            except ValueError:
                return os.path.basename(project_path)
        return project_path

    def test_filter_name(self, test, test_file_path):
        test_class_name = test.get("test_class_name") or os.path.splitext(os.path.basename(test_file_path))[0]
        test_namespace = test.get("test_namespace")
        return f"{test_namespace}.{test_class_name}" if test_namespace else test_class_name

    def build_execution_results(self, result, comp_errors=None, parsed_file=""):
        exec_results = ExecutionResults()
        exec_results.results = result
        exec_results.results_numbers = (len(result[0]), len(result[1]), len(result[2]))
        exec_results.comp_errors = comp_errors
        exec_results.parsed_file = parsed_file or comp_errors or ""
        exec_results.comp_error_matches = [comp_errors] if comp_errors else []
        return exec_results

    def log_modification(self, output_path, context, process):
        os.makedirs(output_path, exist_ok=True)
        with open(os.path.join(output_path, "log.txt"), "a", encoding="utf-8") as file:
            file.write("Modifying context with id: " + str(context.get("id", "")) + "\n")
            file.write(process.stdout + "\n")
            file.write(process.stderr + "\n")

    def shell_quote(self, value):
        return "'" + str(value).replace("'", "'\"'\"'") + "'"
