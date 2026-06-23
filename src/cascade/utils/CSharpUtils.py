import os
import re
import subprocess
import tempfile

TEST_FRAMEWORK_XUNIT = "xunit"
TEST_FRAMEWORK_NUNIT = "nunit"
TEST_FRAMEWORK_MSTEST = "mstest"


def default_tool_path():
    return os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "resources",
            "tools",
            "CSharpTool",
            "CSharpTool.dll",
        )
    )


def resolve_tool_path(tool_path=None, require_exists=True):
    candidate = tool_path or os.environ.get("CASCADE_CSHARP_TOOL") or default_tool_path()
    candidate = os.path.abspath(os.path.expanduser(candidate))

    if require_exists and not os.path.isfile(candidate):
        raise FileNotFoundError(
            "CSharpTool.dll was not found. Set CASCADE_CSHARP_TOOL to the tool path "
            f"or place it at the bundled default path: {default_tool_path()}"
        )

    return candidate


def dotnet_tool_env():
    env = os.environ.copy()
    env.setdefault("DOTNET_ROLL_FORWARD", "Major")
    return env


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parent_context(context):
    parent = context.get("parent", {})
    if isinstance(parent, list):
        return parent[-1] if parent else {}
    return parent or {}


def build_context(context, doc=False, no_fields=False, no_other_method_docs=False,
                  no_other_methods=False, no_constructors=False):
    parent = parent_context(context)
    class_name = parent.get("name", "TargetClass")
    kind = parent.get("kind") or parent.get("parent_type") or "class"
    kind = str(kind).lower()
    if kind not in {"class", "struct", "interface", "record"}:
        kind = "class"

    modifiers = as_list(parent.get("modifier") or parent.get("modifiers") or ["public"])
    generics = as_list(parent.get("generics"))
    extends = parent.get("extends") or parent.get("base") or ""
    implements = as_list(parent.get("implements") or parent.get("interfaces"))
    base_list = [item for item in [extends] + implements if item]

    generic_string = f"<{', '.join(generics)}>" if generics else ""
    base_string = f" : {', '.join(base_list)}" if base_list else ""
    class_declaration = (
        f"{' '.join(modifiers)} {kind} {class_name}{generic_string}{base_string}\n"
        "{\n"
    )

    fields = as_list(parent.get("variables") or parent.get("fields"))
    field_string = ""
    if fields and not no_fields:
        field_string = "".join(format_member(field) for field in fields) + "\n"

    constructors = as_list(parent.get("constructors"))
    constructor_string = ""
    if constructors and not no_constructors:
        constructor_string = "".join(format_member(constructor) for constructor in constructors) + "\n"

    other_methods = ""
    if not no_other_methods:
        for other in as_list(parent.get("other_methods")):
            other_methods += indent_block(build_signature(other, doc=(not no_other_method_docs))) + ";\n\n"

    signature = indent_block(build_signature(context, doc=doc))
    return class_declaration + field_string + constructor_string + other_methods + signature


def format_member(member):
    text = str(member).rstrip()
    if not text:
        return ""
    return indent_block(text) + "\n"


def indent_block(text, indent="    "):
    return "\n".join((indent + line) if line else line for line in str(text).splitlines())


def build_signature(method_context, doc=False):
    documentation = method_context.get("doc", "")
    signature = method_context["signature"]

    result = ""
    if doc and documentation:
        result += documentation.rstrip() + "\n"

    attributes = as_list(signature.get("attributes"))
    for attribute in attributes:
        result += str(attribute).rstrip() + "\n"

    modifiers = " ".join(as_list(signature.get("modifier") or signature.get("modifiers")))
    returns = signature.get("returns") or "void"
    name = signature["name"]
    generics = as_list(signature.get("generics"))
    params = ", ".join(as_list(signature.get("params")))
    constraints = as_list(signature.get("constraints") or signature.get("where"))

    generic_string = f"<{', '.join(generics)}>" if generics else ""
    modifier_prefix = f"{modifiers} " if modifiers else ""
    result += f"{modifier_prefix}{returns} {name}{generic_string}({params})"

    if constraints:
        result += " " + " ".join(str(constraint).strip() for constraint in constraints)

    return result


def csharp_test_name(name):
    name = re.sub(r"^(test_?|Test_?|TEST_?)", "", str(name).strip())
    parts = re.split(r"[^0-9a-zA-Z]+", name)
    normalized = "".join(part[:1].upper() + part[1:] for part in parts if part)
    if not normalized:
        normalized = "GeneratedCase"
    if normalized[0].isdigit():
        normalized = "Case" + normalized
    return "Test" + normalized


def normalize_test_framework(framework):
    framework = str(framework or "xUnit").lower()
    if "nunit" in framework:
        return TEST_FRAMEWORK_NUNIT
    if "mstest" in framework or "ms test" in framework:
        return TEST_FRAMEWORK_MSTEST
    return TEST_FRAMEWORK_XUNIT


def build_tests(context, primer="", no_method=False):
    test = (context.get("tests") or [{}])[0]
    framework = normalize_test_framework(test.get("test_runner") or context.get("test_runner"))
    imports = as_list(test.get("test_imports") or context.get("test_imports"))

    using_lines = []
    for import_line in imports:
        import_line = str(import_line).strip()
        if not import_line:
            continue
        if not import_line.endswith(";"):
            import_line += ";"
        using_lines.append(import_line)

    required_using = {
        TEST_FRAMEWORK_XUNIT: "using Xunit;",
        TEST_FRAMEWORK_NUNIT: "using NUnit.Framework;",
        TEST_FRAMEWORK_MSTEST: "using Microsoft.VisualStudio.TestTools.UnitTesting;",
    }[framework]
    if required_using not in using_lines:
        using_lines.append(required_using)

    usings = "\n".join(using_lines) + "\n\n" if using_lines else ""
    namespace = test.get("test_namespace") or context.get("test_namespace")
    if not namespace:
        parent_namespace = parent_context(context).get("namespace")
        namespace = f"{parent_namespace}.Tests" if parent_namespace else "Cascade.GeneratedTests"

    class_name = (
        test.get("test_class_name")
        or class_name_from_path(test.get("test_file_path") or context.get("test_file_path"))
        or f"{parent_context(context).get('name', 'Generated')}Test"
    )

    class_annotations = []
    method_attribute = "[Fact]"
    if framework == TEST_FRAMEWORK_NUNIT:
        class_annotations.append("[TestFixture]")
        method_attribute = "[Test]"
    elif framework == TEST_FRAMEWORK_MSTEST:
        class_annotations.append("[TestClass]")
        method_attribute = "[TestMethod]"

    body = ""
    if primer:
        body += indent_block(primer.strip("\n")) + "\n"

    if not no_method:
        for test_case in context.get("test_list", []):
            test_name = csharp_test_name(test_case.get("test_name", "GeneratedCase"))
            description = str(test_case.get("test_description", "")).replace("\n", " ")
            body += (
                f"    {method_attribute}\n"
                f"    public void {test_name}()\n"
                "    {\n"
                f"        // {description}\n"
                "    }\n\n"
            )

        if not context.get("test_list"):
            body += build_test_first_method(context["signature"]["name"], method_attribute=method_attribute)

    annotation_string = "".join(annotation + "\n" for annotation in class_annotations)
    return (
        f"{usings}namespace {namespace}\n"
        "{\n\n"
        f"{annotation_string}public class {class_name}\n"
        "{\n"
        f"{body.rstrip()}\n"
        "}\n"
        "}"
    )


def build_test_first_method(signature_name, method_attribute="[Fact]"):
    return (
        f"    {method_attribute}\n"
        f"    public void {csharp_test_name(signature_name)}()\n"
        "    {\n"
        "    }\n"
    )


def class_name_from_path(path):
    if not path:
        return None
    return os.path.splitext(os.path.basename(path))[0]


def check_syntax(code, output_path, tool_path=None):
    tool_path = resolve_tool_path(tool_path)
    os.makedirs(output_path, exist_ok=True)

    temp_file = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cs", delete=False, encoding="utf-8") as file:
            file.write(code)
            temp_file = file.name

        process = subprocess.run(
            ["dotnet", tool_path, "verify", temp_file],
            capture_output=True,
            text=True,
            env=dotnet_tool_env(),
        )

        with open(os.path.join(output_path, "log.txt"), "a", encoding="utf-8") as file:
            file.write("csharp syntax check returned with:" + str(process.returncode) + "\n")
            file.write(code + "\n")
            file.write(process.stdout + "\n")
            file.write(process.stderr + "\n")

        return process.returncode == 0
    finally:
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)


def run_extraction(input_path, output_path, target_framework, tool_path=None):
    tool_path = resolve_tool_path(tool_path)
    os.makedirs(output_path, exist_ok=True)

    process = subprocess.run(
        ["dotnet", tool_path, "extract", input_path, output_path, target_framework],
        capture_output=True,
        text=True,
        env=dotnet_tool_env(),
    )

    with open(os.path.join(output_path, "log.txt"), "a", encoding="utf-8") as file:
        file.write("csharp extraction returned with:" + str(process.returncode) + "\n")
        file.write(process.stdout + "\n")
        file.write(process.stderr + "\n")

    if process.returncode != 0:
        raise RuntimeError(
            "CSharpTool extraction failed.\n"
            f"stdout:\n{process.stdout}\n"
            f"stderr:\n{process.stderr}"
        )


def run_modification(project_dir, entry, code, tests, tool_path=None):
    tool_path = resolve_tool_path(tool_path)
    return subprocess.run(
        ["dotnet", tool_path, "modify", project_dir, entry, code, tests],
        text=True,
        capture_output=True,
        env=dotnet_tool_env(),
    )
