import re
from cascade.analysis.executor.ExecutionResults import ExecutionResults
from cascade.analysis.executor.builders.Builder import Builder
from cascade.utils.DockerizedWrapper import DockerizedWrapper
import xml.etree.ElementTree as ET

class CSharpTestResultParser:
    def parse(self, output):
        results = ExecutionResults()
        results.parsed_file = output

        if self.has_compilation_error(output):
            results.comp_errors = output

        try:
            passed, failed, errored = self.parse_trx(output)
        except ET.ParseError:
            results.comp_errors = output
            results.results = ([], [], ["trx_parse_error"])
            results.results_numbers = (0, 0, 1)
            return results

        results.results = (passed, failed, errored)
        results.results_numbers = (len(passed), len(failed), len(errored))
        return results


    def parse_trx(self, trx_xml):
        # Define the namespace used in the XML
        namespace = {'vs': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}

        root = ET.fromstring(trx_xml)

        passed_tests = []
        failed_tests = []
        errored_tests = []

        for test_result in root.findall('.//vs:UnitTestResult', namespace):
            test_name = test_result.get('testName')
            test_name = test_name.split('.')[-1]  # only use the method name
            test_name = test_name.split('(')[0]
            outcome = test_result.get('outcome')

            # Categorize based on the outcome
            if outcome == 'Passed':
                passed_tests.append(test_name)
            elif outcome == 'Failed':
                failed_tests.append(test_name)
            elif outcome == 'Error':
                errored_tests.append(test_name)

        return passed_tests, failed_tests, errored_tests
    

    def has_compilation_error(self, output):
        return "Build FAILED" in output or "error CS" in output


class CSharpBuilder(Builder):
    def __init__(self, image,
                 new_image_name,
                 dotnet_args, 
                 set_up_command,
                 set_up_args,
                 timeout = 300
                 ):
        self.parser = CSharpTestResultParser()
        super().__init__(
            pattern = (
            f"echo \"[INFO] Tests run starting!\" > out; "
            f"timeout {timeout} dotnet test {dotnet_args} > output 2>&1; "
            "status=$?; cat output > out; "
            "echo \"[INFO] Exit code: $status\" >> out; "
            "cat output"
            ),
            eval_function=self.eval_function,
            image=new_image_name
        )
        self.old_image_name = image
        self.set_up_commands = set_up_command
        self.set_up_args = set_up_args

    def eval_function(self, output):
        return self.parser.parse(output)
    
    def set_up(self, temp_dir, context, output_path):
        wrapper = DockerizedWrapper()
        dock_context = {
            "image": self.old_image_name,
            "new_image": self.image,
            "directory": temp_dir,
            "command": f"{self.set_up_command} {self.set_up_args}; RET=$?; rm -rf ../root/*; exit $RET;",
        }
        return wrapper.setup_image(dock_context, output_path)
    
    def tear_down(self, _):
        """Remove the temporary Docker image created during `set_up`."""
        wrapper = DockerizedWrapper()
        dock_context = {
            "new_image": self.image,
        }
        wrapper.remove_image(dock_context)