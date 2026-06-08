import os
import json
import ast
import subprocess

ROOT_MODULE = "root module"


def indent_block(text, indent):
    if not indent:
        return text

    return "\n".join((indent + line) if line else line for line in text.splitlines())


def build_context(context, doc=False, imports=False, no_fields=False, no_other_method_docs=False,
                  no_other_methods=False, no_constructors=False):
    parents = context["parent"]
    if isinstance(parents, dict):
        parents = [parents]

    result = ""
    indent = ""

    for index, parent in enumerate(parents):
        result += build_parent_header(parent, imports=(imports and index == 0), indent=indent)

        if parent.get("parent_type") == "Class" and parent.get("name") != ROOT_MODULE:
            indent += "    "

        if not no_fields:
            result += build_variables(parent.get("variables", []), indent=indent)

        if not no_constructors:
            result += build_other_methods(parent.get("constructors", []), doc=(not no_other_method_docs),
                                          indent=indent)

        result += build_other_methods(parent.get("other_methods", []), doc=(not no_other_method_docs),
                                      indent=indent, no_other_methods=no_other_methods)

    result += indent_block(build_signature(context, doc), indent)

    return result


def build_parent_header(parent, imports=False, indent=""):
    result = ""

    if imports:
        imports_ = parent.get("imports", [])
        result += "".join(imports_)
        if imports_:
            result += "\n"

    if parent.get("parent_type") != "Class" or parent.get("name") == ROOT_MODULE:
        return result

    for decorator in parent.get("decorators", []):
        result += indent + decorator + "\n"

    bases = parent.get("bases", [])
    bases_string = f"({', '.join(bases)})" if bases else ""
    result += indent + f"class {parent['name']}{bases_string}:\n"

    return result


def build_variables(variables, indent=""):
    if not variables:
        return ""

    variable_string = "".join(indent + variable.rstrip() + "\n" for variable in variables)
    return variable_string + "\n"


def build_other_methods(methods, doc=False, indent="", no_other_methods=False):
    if no_other_methods:
        return ""

    result = ""
    for method in methods or []:
        result += indent_block(build_signature(method, doc=doc), indent) + "\n"
        result += indent + "    pass\n\n"

    return result

def build_signature(method_context, doc=False):
    doc_string = method_context.get("doc", "")
    sig = method_context["signature"]

    result = ""
    if doc and doc_string:
        result += doc_string.rstrip() + "\n"

    for decorator in sig.get("decorators", []):
        result += decorator + "\n"

    async_prefix = "async " if sig.get("is_async", False) else ""
    params = ", ".join(sig.get("params", []))
    returns = sig.get("returns", "")
    return_string = f" -> {returns}" if returns else ""

    result += f"{async_prefix}def {sig['name']}({params}){return_string}:"

    return result

def check_syntax(code, type, output_path):
    """
    Checks if a piece of Python code is syntactically correct by parsing it with
    Python's ast module. The output is logged to log.txt in the output_path.

    :param code: the string containing the Python code to check
    :param type: kept for API compatibility; ignored for Python
    :param output_path: directory where log.txt should be written
    :return: True if the given code is syntactically correct, False otherwise
    """
    syntax_error = None
    try:
        ast.parse(code)
        result = True
    except SyntaxError as e:
        syntax_error = str(e)
        result = False

    if output_path:
        with open(os.path.join(output_path, "log.txt"), "a") as file:
            file.write("python syntax check returned with:" + str(result) + "\n")
            file.write(code + "\n")
            if syntax_error:
                file.write(syntax_error + "\n")

    return result

def get_repair_helper_functions():
    """
    Returns the available functions that can be used for tool usage of common LLM APIs.
    """
    def build_tool_description(name, description, parameters):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "strict": True,
                "parameters": {
                    "type": "object",
                    "required": [*map(lambda x: x[0], parameters)],
                    "properties": {
                        **{x[0]: {"type": x[1], "description": x[2]} for x in parameters}
                    },
                    "additionalProperties": False
                }
            }
        }

    t1 = build_tool_description(
        "get_file_content",
        "Gets the entire content of a specific Python file.",
        [
            ("path_to_file", "string", "The relative path to the Python file")
        ]
    )

    t2 = build_tool_description(
        "get_module_functions",
        "Gets a list of top-level functions from a Python module.",
        [
            ("path_to_file", "string", "The relative path to the Python module"),
            ("private_included", "boolean", "Should private functions starting with '_' be included?")
        ]
    )

    t3 = build_tool_description(
        "get_class_methods",
        "Gets a list of methods from a Python class.",
        [
            ("path_to_file", "string", "The relative path to the Python module"),
            ("class_name", "string", "The name of the Python class"),
            ("private_included", "boolean", "Should private methods starting with '_' be included?")
        ]
    )

    t4 = build_tool_description(
        "get_class_attributes",
        "Gets class-level attributes and annotated attributes from a Python class.",
        [
            ("path_to_file", "string", "The relative path to the Python module"),
            ("class_name", "string", "The name of the Python class")
        ]
    )

    t5 = build_tool_description(
        "get_imports",
        "Gets import statements from a Python module.",
        [
            ("path_to_file", "string", "The relative path to the Python module")
        ]
    )

    return [t1, t2, t3, t4, t5]

def repair_helper_functions(func, arguments, input_path, output_path, context):
    arguments = json.loads(arguments)
    functions = {"get_file_content": get_file_content,
                 "get_module_functions": get_module_functions,
                 "get_class_methods": get_class_methods,
                 "get_class_attributes": get_class_attributes,
                 "get_imports": get_imports}

    if func not in functions:
        return {"error": f"Unknown repair helper function: {func}"}

    try:
        return functions[func](input_path, output_path, context, **arguments)
    except Exception as e:
        return {"error": str(e)}

def get_file_content(input_path, output_path, context, path_to_file):
    if path_to_file in [context.get("test_file_path"), context.get("code_file_path")]:
        return { "content" : "", "error" : "path prohibited" }

    path = os.path.join( input_path, path_to_file)
    if os.path.exists(path):
        with open(path, "r") as f:
            return {"content" : f.read()}
    else:
        return {"content" : "", "error" : "file does not exist"}

def get_module_functions(input_path, output_path, context, path_to_file, private_included):
    data = load_extracted_data(output_path)
    returns = []

    for d in data:
        if d.get("code_file_path") != path_to_file:
            continue

        parents = d.get("parent", [])
        if isinstance(parents, dict):
            parents = [parents]

        is_module_level = not parents or parents[-1].get("parent_type") == "Module"
        name = d.get("signature", {}).get("name", "")

        if is_module_level and (private_included or not name.startswith("_")):
            returns.append(build_signature(d))

    return {"functions": returns}

def get_class_methods(input_path, output_path, context, path_to_file, class_name, private_included):
    data = load_extracted_data(output_path)
    returns = []

    for d in data:
        if d.get("code_file_path") != path_to_file:
            continue

        parents = d.get("parent", [])
        if isinstance(parents, dict):
            parents = [parents]

        parent = parents[-1] if parents else {}
        name = d.get("signature", {}).get("name", "")

        if parent.get("parent_type") == "Class" and parent.get("name") == class_name and (private_included or not name.startswith("_")):
            returns.append(build_signature(d))

    return { "methods" : list(returns)}

def get_class_attributes(input_path, output_path, context, path_to_file, class_name):
    data = load_extracted_data(output_path)

    for d in data:
        if d.get("code_file_path") != path_to_file:
            continue

        parents = d.get("parent", [])
        if isinstance(parents, dict):
            parents = [parents]

        for parent in parents:
            if parent.get("parent_type") == "Class" and parent.get("name") == class_name:
                return {"attributes": parent.get("variables", [])}

    return {"attributes": []}

def get_imports(input_path, output_path, context, path_to_file):
    data = load_extracted_data(output_path)

    for d in data:
        if d.get("code_file_path") != path_to_file:
            continue

        parents = d.get("parent", [])
        if isinstance(parents, dict):
            parents = [parents]

        if parents:
            return {"imports": parents[0].get("imports", [])}

    return {"imports": []}


def load_extracted_data(output_path):
    extracted_path = os.path.join(output_path, "extracted.json")
    if not os.path.exists(extracted_path):
        return []

    with open(extracted_path, "r") as f:
        return json.load(f)
