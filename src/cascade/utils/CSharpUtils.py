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

    #TODO: include body?
    return complete_method

def build_tests(context, primer=""):
    # TODO: Think about using multiple test files?
    test = context["tests"][0]
    framework = str(test["test_runner"])

    usings = '\n'.join(test["test_imports"]) + '\n' if test["test_imports"] else ""
    namespace = '\n' + "namespace " + test["test_namespace"] + ";\n\n"

    class_name = test["test_file_path"].split("/")[-1].split(".")[0]
    class_definition = "public class " + class_name + "\n{"
    name = str(context["signature"]["name"])
    test_method = "\n    public void " + name[0].upper() + name[1:] + "_Test_1()\n{"

    class_definition += primer # always include primer prior to method declaration

    if framework == TEST_FRAMEWORK_XUNIT:
        annotation = "\n    [Fact]"
        return usings + namespace + class_definition + annotation + test_method

    elif framework == TEST_FRAMEWORK_NUNIT:
        class_annotation = "[TestFixture]\n"
        annotation = "\n    [Test]"
        return usings + namespace + class_annotation + class_definition + annotation + test_method

    elif framework == TEST_FRAMEWORK_MSTEST:
        class_annotation = "[TestClass]\n"
        annotation = "\n    [TestMethod]"
        return usings + namespace + class_annotation + class_definition + annotation + test_method

    else:
        raise Exception("No valid test runner defined")


def check_syntax(code, type, output_path):
    """

    :param code:
    :param type:   should be "block" or "class"
    :return:
    """
    print("TODO: implement syntax check for C#!")
    pass


#TODO: remove after testing
import json

def main():
    file_path = '/Users/mar/Desktop/Masterarbeit/extracted.json'

    with open(file_path, 'r') as file:
        json_data = json.load(file)
        for json_object in json_data:
            print(build_tests(json_object, primer="\n    // start writing tests for FUNCTIONNAME here"))
            print("\n------\n")

# Run the main function
if __name__ == '__main__':
    main()

