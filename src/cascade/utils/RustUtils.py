import os
import subprocess

ROOT_MODULE: str = "root module"
INJECTED_SUITE_PATH: str = "tests/DedicatedTestSuiteOfCASCADE.rs"
INJECTED_SUITE_NAME: str = "DedicatedTestSuiteOfCASCADE"
INJECTED_MODULE_NAME: str = "injected_test_mod_cascade"

def build_context(context, doc=False, no_fields=False, no_other_method_docs=False , no_other_methods=False):
    result = ""

    parents = context["parent"]
    for parent in parents:
        result += build_parent(parent, no_other_method_docs, no_other_methods, no_fields)

    result += build_signature(context, doc)
    result += ("\n}" * (len(parents) - 1))

    return result

def build_parent(parent, no_other_method_docs, no_other_methods, no_fields):
    parent_name = ""  # root module has no name
    if parent["name"] != ROOT_MODULE:
        parent_type = parent["parent_type"]
        parent_type_suffix = "mod " if parent_type == "Module" else ""
        parent_name = parent_type_suffix + parent["name"] + " {\n"

    imports = "\n".join(parent["imports"])
    attributes = "\n".join(parent["attributes"])
    variables = "\n".join(parent["variables"]) if not no_fields else None

    other_methods = ""
    for other in (parent["other_methods"] if not no_other_methods else []):
        other_method = "\n" + build_signature(other, doc=(not no_other_method_docs))
        other_methods += remove_trailing_comma(other_method) + ";\n"

    return (
               (attributes + "\n" if attributes else "")
               + parent_name
               + (imports + "\n" if imports else "")
               + (variables + "\n" if variables else "")
               + (other_methods + "\n" if other_methods else "")
               + "\n"
           )


def build_signature(method_context, doc=False):
    documentation = method_context["doc"]
    documentation_string = documentation + "\n" if doc and documentation else ""

    sig = method_context["signature"]
    annotations = sig["annotations"] #array
    modifier = sig["modifier"]
    name = sig["name"]
    params = sig["params"] #array
    return_type = sig["returns"]
    traits = sig["traits"]


    complete_method = (  documentation_string
                       + "\n".join(annotations) + ("\n" if annotations else "")
                       + ((modifier + " ") if modifier else "")
                       + "fn " + name
                       + "(" + ", ".join(params) + ") "
                       + return_type + " "
                       + traits )

    return complete_method


def build_replacement_test_dict_with_path(test_file_path):
    replacement_test_dict = {
        "test_file_path": test_file_path,
        "tests": "",
        "test_imports": [],
        "test_class_name": "",
        "test_runner": "",
        "test_as_context": None,
        "test_type": "",
        "project_path": "",
        "test_namespace": "",
    }
    return replacement_test_dict

def contains_ignore_whitespace(text, substring):
    text_norm = text.replace(" ", "")
    substring_norm = substring.replace(" ", "")
    return substring_norm in text_norm

# This is only used if no original tests exist
def build_test_suite(context, primer="", no_method=False):
    use_statement = context["use_statement_path"]
    result = use_statement + "\n"

    # build test method with primer
    method = (primer + "\n" +
              build_test_first_method(context))

    return result + ("" if no_method else method)

# This is only used if no original tests exist
def build_test_module(context, primer="", no_method=False):
    test_module_to_inject = ("#[cfg(test)]\n"
                             + "mod " + INJECTED_MODULE_NAME + " {\n"
                             + "use super::*;\n")

    method = (primer + "\n" +
              build_test_first_method(context))

    return test_module_to_inject + ("" if no_method else method)


def build_tests(context, primer="", no_method=False):
    test = context["tests"][0]
    test_as_context = test["test_as_context"]

    result = ""

    parents = test_as_context["parent"]
    for parent in parents:
        result += build_parent(parent, True, False, False)

    # build test method with primer
    method = (primer + "\n" +
              build_test_first_method(context))

    return result + ("" if no_method else method)

def build_test_first_method(context):
    return "#[test]\nfn " + context["signature"]["name"] + "_test_1() {"

def remove_trailing_comma(s: str) -> str:
    return s[:-1] if s.endswith(",") else s

def check_syntax(code, output_path) -> bool:
    """
    :param code: Rust code to check syntactically
    :param output_path: destination of log file
    :return:
    """
    temp_file = "temp.rs"
    with open(temp_file, "w") as file:
        file.write(code)

    my_path = os.path.dirname(__file__)
    p = subprocess.run(
        [
            os.path.join(my_path, "..", "resources", "tools", "rust-tool"),
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

def run_extraction(input_path, output_path):
    """
    :param input_path: project to extract from
    :param output_path: location to place the final extracted.json
    """
    my_path = os.path.dirname(__file__)
    subprocess.run(
        [
            os.path.join(my_path, "..", "resources", "tools", "rust-tool"),
            "extract",
            input_path,
            output_path],
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
        [
            os.path.join(my_path, "..", "resources", "tools", "rust-tool"),
            "modify",
            project_dir,
            entry,
            code,
            tests],
        text=True,
        capture_output=True
    )