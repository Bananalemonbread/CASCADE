from cascade.analysis.executor.builders.Builder import Builder
from cascade.utils.DockerizedWrapper import DockerizedWrapper
import re

class RustBuilder(Builder):
    def __init__(self,
                 image,
                 new_image_name,
                 set_up_command,
                 set_up_args):
        super().__init__(eval_function=self.eval_function,image=image)
        self.image = image
        self.new_image_name = new_image_name
        self.set_up_command = set_up_command
        self.set_up_args = set_up_args

    def eval_function(self, output):
        """
        The function that has to be given to the builder to evaluate the output of the tests
        :param output: a string containing the output produced in the docker,
                    which should contain the output of the tests which are then parsed here.
        :return: result a tuple of three lists of strings,
            the first list contains the names of the tests that passed,
            the second list contains the names of the tests that failed,
            the third list contains the names of the tests that errored
        """

        passed_tests = []
        failed_tests = []
        errored_tests = []

        # Check for compilation or setup failure
        if "error: could not compile" in output or "error: build failed" in output:
            errored_tests.append("Compilation error")
        else:
            test_results = re.findall(r"test (\S+) \.\.\. (ok|FAILED)", output)

            for test_name, outcome in test_results:
                if outcome == "ok":
                    passed_tests.append(test_name)
                elif outcome == "FAILED":
                    failed_tests.append(test_name)

        return [passed_tests, failed_tests, errored_tests]

    def set_up(self, temp_dir, _, output_path):
        wrapper = DockerizedWrapper(debug=True)
        dock_context = {
            "image": self.image,
            "new_image": self.new_image_name,  # name of the new image that results
            "directory": temp_dir,
            #"command": f"{self.set_up_command} {self.set_up_args}; RET=$?; rm -rf ../root/*; exit $RET;",
            "command": f"{self.set_up_command} {self.set_up_args}; RET=$?; exit $RET;",
        }
        return wrapper.setup_image(dock_context, output_path)

    def tear_down(self, _):
        wrapper = DockerizedWrapper(debug=True)
        dock_context = {
            "new_image": self.new_image_name,
        }
        wrapper.remove_image(dock_context)

