from cascade.analysis.executor.builders.Builder import Builder
from cascade.utils.DockerizedWrapper import DockerizedWrapper
import xml.etree.ElementTree as ET

def parse_xml_result(xml):
    # Define the namespace used in the XML
    namespace = {'vs': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}

    root = ET.fromstring(xml)

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

    return [passed_tests, failed_tests, errored_tests]

class CSharpBuilder(Builder):
    def __init__(self,
                 image,
                 new_image_name,
                 dotnet_args,
                 set_up_command,
                 set_up_args,
                 timeout=120):
        pattern = f"echo \"[INFO] Tests run starting!\" > out; timeout {timeout} dotnet test {dotnet_args} 2>&1 > output; cat output > out; cat output"
        super().__init__(pattern, self.eval_function, image)
        self.image = image
        self.new_image_name = new_image_name
        self.set_up_command = set_up_command
        self.set_up_args = set_up_args

    def eval_function(self, x):
        """
        The function that has to be given to the builder to evaluate the output of the tests
        :param x: a string containing the output produced in the docker,
                    which should contain the output of the tests which are then parsed here.
        :return: result a tuple of three lists of strings,
            the first list contains the names of the tests that passed,
            the second list contains the names of the tests that failed,
            the third list contains the names of the tests that errored
        """

        return parse_xml_result(x)

    def set_up(self, temp_dir, _, output_path):
        wrapper = DockerizedWrapper(debug=True)
        dock_context = {
            "image": self.image,
            "new_image": self.new_image_name,  # name of the new image that results
            "directory": temp_dir,
            "command": f"{self.set_up_command} {self.set_up_args}; RET=$?; rm -rf ../root/*; exit $RET;",
        }
        return wrapper.setup_image(dock_context, output_path)

    def tear_down(self, _):
        wrapper = DockerizedWrapper(debug=True)
        dock_context = {
            "new_image": self.image,
        }
        wrapper.remove_image(dock_context)
