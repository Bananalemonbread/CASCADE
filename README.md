## 1 Overview

This repository contains **CASCADE** (our code-comment inconsistency detection and test-generation tool) 
together with the full benchmark we used to evaluate it in our FSE 2026 Paper. (folder: `PaperEvaluation`)

The tool itself is build around expandability, so that you can easily add new validation approaches to the benchmark
Or adapt it for new languages and for different analyses.


If you want to run the benchmark from scratch, you can follow the instructions in `PaperEvaluation/README.md`

If you want to try out CASCADE on your own projects, you can follow the instructions in section 4.

An example Java project you can try it on is described in Section 6.



---

## 2  Repository layout

```
.
├─ PaperEvaluation/
│  ├─ dataset.zip           # Evaluation dataset (see Section 3 for details)
│  ├─ drivers/              # One sub‑folder per validation approach (see Section 4 for details)
│  │   ├─ DocChecker/
│  │   ├─ Baseline/
│  │   └─ CASCADE/
│  ├─ run.sh                # dataset execution file (runs all drivers on the dataset)
│  ├─ eval.py               # Computes & prints all benchmark metrics
│  └─ results.zip       # Pre‑computed experiment results
├─ datasetExtraction/       # scripts we used to extract the original dataset
├─ configs/                 # Configuration files for different CASCADE pipelines
└─ src/                     # Source code of the CASCADE tool


````

## 3  `src/` directory structure

The main implementation lives in `src/cascade/`, which contains the code that wires the CASCADE pipeline together.

- `Pipeline.py` and `PipelineFactory.py` orchestrate the end-to-end workflow and build pipeline instances from configuration.
- `CLI.py` provides the command-line entry point, and `build.py` contains build/helper logic used by the project.
- `analysis/` contains the analysis layer, including the abstractions and concrete analysis implementations.
- `extraction/` contains the extraction layer, which reads input projects or datasets and produces structured data.
- `filters/` contains filtering logic used to discard items that do not meet the desired criteria.
- `generation/` contains code, test, and documentation generators, grouped into `code/`, `test/`, and `doc/` subfolders.
- `utils/` contains shared helper functions and utilities used across the project.
- `resources/` stores bundled assets such as external tools and other project resources.


## 4  Running CASCADE

CASCADE can be built and run as a standalone tool.

### 4.1 Install

Create a virtual environment:

```bash
python3 -m venv cascade.venv
```

If you are inside the main CASCADE folder (on one level with src and setup.py) install it directly into the venv with:

```bash
./cascade.venv/bin/pip install .
```

CASCADE requires an OpenAI key in the environment.
Even if you do not plan to use an LLM-based analysis, the key is still needed for some generator-based workflows.
If you only want to do a local smoke test, you can set a dummy value.

```bash
export OPENAI_API_KEY=<your key>
```

### 4.2 Run command format

General command:

```bash
./cascade.venv/bin/CASCADE run -i "<input-project-root>" -o "<output-folder>" -c "<config.json>"
```

You can use CLI overrides to replace values in the config file at runtime.

For example, to change the LLM temperature for the code generator, use:

```bash
./cascade.venv/bin/CASCADE run -i "<input-project-root>" -o "<output-folder>" -c "<config.json>" --code-generator temperature:0.7
```

To run CASCADE on a project, you provide:
- The root of the Java project that should be analyzed.
- an output directory and
- a config file that references the components you want to use (`configs/` contains examples),


CASCADE then:
1. extracts method-level context from the project,
2. applies filters, for example to remove methods without documentation or code,
3. runs the analysis step, which may include generation and execution of tests or code snippets.


See Section 5 for a runnable example project and config file you can try out.


## 5  Example project

A tiny runnable example is included in `exampleTargetproject/`.

It contains one Java class with 4 functions:

- `add(int a, int b)`: doc and implementation are consistent.
- `subtract(int a, int b)`: doc says subtraction, implementation multiplies (intentional inconsistency).
- `dummy1()`: has no documentation
- `dummy2()`: has no code

Files:

- `exampleTargetproject/repository/src/main/java/example/Calculator.java`
- `exampleTargetproject/repository/src/test/java/example/CalculatorTest.java`
- `exampleTargetproject/repository/pom.xml`

### 5.1 Run the example workflow

Run from the repository root. For the Java example:

```bash
../cascade.venv/bin/CASCADE run \
  -i "./examples/java/repository" \
  -o "./examples/java/output" \
  -c "./configs/exampleConfig.json"
```

For the Rust example:

```bash
../cascade.venv/bin/CASCADE run \
  -i "./examples/rust" \
  -o "./examples/rust/output" \
  -c "./configs/Rust.json"
```

### 5.2 What happens in this example

1. **Extraction**: CASCADE reads the Java project and extracts method-level context for `Calculator`.
2. **Filtering**: functions that do not match the configured filters are removed (the two dummy methods).
3. **mvn Setup**: a mvn image is setup that will be used in all dockers that are dynamically setup to execute tests.
4. **Analysis**: the configured analysis step runs on the remaining methods. this one generates tests and code as described in our Paper.
5. **Execution**: if you use the LLM-backed config, CASCADE generates tests/code and executes them through the Maven/Docker executor.
6. **Output**: the results are saved in the output folder, including the extracted methods, the analysed file with all generated artifacts and the final inconsistency predictions. (also a large log file)
7. 
### 5.3 Output files

Depending on the selected config, the example folder will contain files such as:

- `extracted.json`: extracted method-level context.
- `analyzed.json`: analysis output and generated artifacts.
- `inconsistent_functions.json`: functions labeled as inconsistent, together with file and test-case details.

The basic output line for a function looks like this:\
example: \
INCO; pass; step 2 (C'+T'); (2,1,0);(3,0,0); p2p: 2, f2f: 0, p2f: 0, f2p: 1

explanation:\
INCO/NoInco; pass/fail/error/; stage of thispass/fail/error; (#num of passing tests, #failing tests, #error tests) for step1; (#num of pass tests, #fail, #error) for step2; explicit metrics for:
1. tests that passed on stage one and passed on stage 2 (p2p)
2. tests that failed on stage one but passed on stage 2 (f2p)
3. tests that passed on stage one but failed on stage 2 (p2f)
4. tests that failed on stage one and failed on stage 2 (f2f)\
(erroring tests are counted as failing)





## 6 Expanding CASCADE

CASCADE is designed to be extended. You can add custom extraction logic, filters, generators, analyses, and executors
without changing the core pipeline orchestration.

The easiest way to extend it is:

1. inherit from the matching abstract base class,
2. put the new class in the right subdirectory (follow one existing implementation as a template),
3. reference your class by name in the config file (`name` + `kwargs`).
4. let the pipline factory handle the rest via the run command

Common extension points and examples:

- **Analysis**: inherit from `src/cascade/analysis/Analysis.py` (example: `JavaTwoStepAnalysis.py`)
- **FilterFunction**: inherit from `src/cascade/filters/FilterFunction.py` (example: `ContainsFilterFunction.py`, `CheckLengthFilterFunction.py`)
- **Generators**: inherit from `src/cascade/generation/Generator.py` in `code/`, `test/`, or `doc/`
  (example: `code/JavaCodeGenerator.py`, `test/GPT4JavaTestGenerator.py`)
- **Executor**: inherit from `src/cascade/analysis/executor/AnalysisExecutor.py`
  (example: `analysis/executor/MavenJavaExecutor.py`, `analysis/executor/JavaExecutor.py`)

the absolute base pipeline is Extraction → (Filter) → Analysis, but you can also add custom generation steps that are not directly tied to the analysis step, for example to generate documentation updates or code snippets without executing them.

If your custom classes are outside `src/cascade`, pass their location with CLI `--module-path`.
`PipelineFactory` loads classes dynamically from the names in your config file.

If you build a cool or useful extension, feel free to open a pull request.
