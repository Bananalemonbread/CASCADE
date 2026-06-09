import os
import subprocess

TEST_FRAMEWORK_XUNIT: str = "xUnit"
TEST_FRAMEWORK_NUNIT: str = "NUnit"
TEST_FRAMEWORK_MSTEST: str = "MSTest"

def build_context(context, doc=False, no_fields=False, no_other_method_docs=False , no_other_methods=False, no_constructors=False):
    generics = context["parent"]["generics"]
    extends = context["parent"]["extends"]
    base_list = context["parent"]["implements"]
    base_list.insert(0, extends)

    class_declaration = (f"public class {context['parent']['name']}{('<' + ', '.join(generics) + '>' if generics else '')}" + ' '
              + f" {(': ' + ', '.join(base_list) + ' ' if extends else '')}{{\n")

    fields = context["parent"]["variables"]
    field_string = ("\n".join(fields) + "\n\n") if not no_fields and fields else ""

    constructors = context["parent"]["constructors"]
    constructor_string = ("\n\n".join(constructors) + "\n") if not no_constructors and constructors else ""

    other_methods = ""
    for other in (context["parent"]["other_methods"] if not no_other_methods else []):
        other_methods += "\n" + build_signature(other, doc=(not no_other_method_docs)) + ";\n"

    signature = build_signature(context, doc)

    context_info = (class_declaration
                    + field_string
                    + constructor_string
                    + other_methods
                    + "\n" + signature)

    return context_info


def build_signature(method_context, doc=False):
    documentation = method_context["doc"]
    documentation_string = documentation + "\n" if doc and documentation else ""
    sig = method_context["signature"]
    generics = sig["generics"]

    complete_method = (documentation_string
                       + " ".join(sig["modifier"])
                       + " " + sig["returns"] + " "
                       + sig["name"]
                       + ('<' + ', '.join(generics) + '> ' if generics else '')
                       + "(" + ", ".join(sig["params"]) + ")")

    return complete_method

def build_tests(context, primer="", no_method=False):
    # TODO: Think about using multiple test files?
    test = context["tests"][0]
    framework = str(test["test_runner"])

    usings = '\n'.join(test["test_imports"]) + '\n' if test["test_imports"] else ""
    namespace = '\n' + "namespace " + test["test_namespace"] + "\n{\n\n"

    class_name = test["test_file_path"].split("/")[-1].split(".")[0]
    class_definition = "public class " + class_name + "\n{"
    test_method = build_test_first_method(context["signature"]["name"])

    class_definition += primer # always include primer prior to method declaration

    if framework == TEST_FRAMEWORK_XUNIT:
        annotation = "\n    [Fact]"
        res = usings + namespace + class_definition
        method = annotation + test_method

    elif framework == TEST_FRAMEWORK_NUNIT:
        class_annotation = "[TestFixture]\n"
        annotation = "\n    [Test]"
        res = usings + namespace + class_annotation + class_definition
        method = annotation + test_method

    elif framework == TEST_FRAMEWORK_MSTEST:
        class_annotation = "[TestClass]\n"
        annotation = "\n    [TestMethod]"
        res = usings + namespace + class_annotation + class_definition
        method = annotation + test_method

    else:
        raise Exception("No valid test runner defined")

    return res + ("" if no_method else method)

def build_test_first_method(signature_name):
    return "\n    public void " + signature_name[0].upper() + signature_name[1:] + "_Test_1()\n{"

def check_syntax(code, output_path):
    """
    :param code: C# code to check syntactically
    :param output_path: destination of log file
    :return:
    """
    temp_file = "temp.cs"
    with open(temp_file, "w") as file:
        file.write(code)

    my_path = os.path.dirname(__file__)
    p = subprocess.run(
        ["dotnet",
         os.path.join(my_path, "..", "resources", "tools", "CSharpTool", "CSharpTool.dll"),
         "verify",
         temp_file],
        capture_output=True,
        text=True
    )

    with open(os.path.join(output_path, "log.txt"), "a") as file:
        file.write("verify returned with:" + str(p.returncode) + "\n")
        file.write(code + "\n")
        file.write(p.stdout + "\n")
        file.write(p.stderr + "\n")

    os.remove(temp_file)

    return p.returncode == 0

def run_extraction(input_path, output_path, target_framework):
    """
    :param input_path: project to extract from
    :param output_path: location to place the final extracted.json
    :param target_framework: the .NET target framework used to compile to project
    """
    my_path = os.path.dirname(__file__)
    subprocess.run(
        ["dotnet",
         os.path.join(my_path, "..", "resources", "tools", "CSharpTool", "CSharpTool.dll"),
         "extract",
         input_path,
         output_path,
         target_framework],
        text=True
    )

def run_modification(project_dir, entry, code, tests):
    """
    :param project_dir: project to modify code and tests
    :param entry: json file containing the required information
        (similar to context + new_code & new_tests fields)
    :param code: keyword to trigger the modification
    :param tests: keyword to trigger the modification
    """

    my_path = os.path.dirname(__file__)
    return subprocess.run(
        ["dotnet",
         os.path.join(my_path, "..", "resources", "tools", "CSharpTool", "CSharpTool.dll"),
         "modify",
         project_dir,
         entry,
         code,
         tests],
        text=True,
        capture_output=True
    )