import os
import subprocess

ROOT_MODULE: str = "root module"

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

def build_tests(context, primer="", no_method=False):
    test = context["tests"][0]
    test_as_context = test["test_as_context"]

    result = ""

    parents = test_as_context["parent"]
    for parent in parents:
        result += build_parent(parent, True, True, False)

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

#################
### TESTING STUFF
#################
"""
import json

json_file_path = "/Users/mar/Desktop/Masterarbeit/extracted.json"

# Load the JSON file into a dictionary
with open(json_file_path, "r", encoding="utf-8") as file:
    data = json.load(file)


p = run_modification("/Users/mar/Desktop/Masterarbeit/dummy_project/testing-rust2", "/Users/mar/Desktop/Masterarbeit/entry.json", "code" , "new_tests")
run_extraction("/Users/mar/Desktop/Masterarbeit/dummy_project/testing-rust2", "/Users/mar/Desktop")
print(check_syntax(build_signature(data[0]) + data[0]["code"][0:], None))
for c in data:
    if len(c["tests"]) > 0:
        print(build_tests(c, "BITTE HIER TEST SCHREIBEN JA?"))
        print("--------\n")
"""
