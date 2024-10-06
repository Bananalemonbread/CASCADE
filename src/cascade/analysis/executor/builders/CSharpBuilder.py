from cascade.analysis.executor.builders.Builder import Builder
from cascade.utils.DockerizedWrapper import DockerizedWrapper
import xml.etree.ElementTree as ET

def parse_xml_result(xml):
    # Define the namespace used in the XML
    namespaces = {'vs': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}

    root = ET.fromstring(xml)
    result_summary = root.find('vs:ResultSummary', namespaces)
    if result_summary is None:
        raise ValueError("Invalid XML: <ResultSummary> element not found")

    counters = result_summary.find('vs:Counters', namespaces)
    if counters is None:
        raise ValueError("Invalid XML: <Counters> element not found")

    results = {
        'total': int(counters.attrib['total']),
        'passed': int(counters.attrib['passed']),
        'failed': int(counters.attrib['failed']),
        'error': int(counters.attrib['error'])
    }

    return results


class CSharpBuilder(Builder):
    def __init__(self,
                 image,
                 new_image_name,
                 dotnet_args,
                 set_up_command,
                 set_up_args,
                 timeout=120):
        pattern = f"echo \"[INFO] Tests run: 0, Failures: 0, Errors: 0, Skipped: 0\" > out; timeout {timeout} dotnet test {dotnet_args} 2>&1 > output; cat output > out; cat output"
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
            the first list contains the ids of the tests that passed,
            the second list contains the ids of the tests that failed,
            the third list contains the ids of the tests that errored
        """

        result = ([], [], [])

        parsed = parse_xml_result(x)

        print("TODO: determine with TOBI")
        #TODO: you can extract the actual method names of the tests



        return result

    def set_up(self, temp_dir, _, output_path):
        wrapper = DockerizedWrapper(debug=True)
        dock_context = {
            "image": self.image,
            "new_image": self.new_image_name,  # name of the new image that results
            "directory": temp_dir,
            "command": f"dotnet {self.set_up_command} {self.set_up_args}; RET=$?; rm -rf ../root/*; exit $RET;",
        }
        return wrapper.setup_image(dock_context, output_path)

    def tear_down(self, _):
        wrapper = DockerizedWrapper(debug=True)
        dock_context = {
            "new_image": self.image,
        }
        wrapper.remove_image(dock_context)

