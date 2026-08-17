#!/usr/bin/env bash

set -uo pipefail

usage() {
	echo "Usage: $0 <java|python|rust|csharp>" >&2
}

case "${1:-}" in
	java|python|rust|csharp)
		LANGUAGE=$1
		;;
	*)
		usage
		exit 2
		;;
esac

CONFIG_FILE="${LANGUAGE}_dataset_config.json"
CASCADE_BIN=${CASCADE_BIN:-CASCADE}

if [[ ! -f "$CONFIG_FILE" ]]; then
	echo "Missing CASCADE configuration: $CONFIG_FILE" >&2
	exit 2
fi

if [[ ! -d repository ]]; then
	echo "Missing checked-out repository directory" >&2
	exit 2
fi

if [[ ! -f analyzed.json ]]; then
	echo "Missing dataset input: analyzed.json" >&2
	exit 2
fi

if [[ $CASCADE_BIN == */* && ! -x $CASCADE_BIN ]]; then
	echo "CASCADE executable not found: $CASCADE_BIN" >&2
	exit 2
fi

# The evaluation runner expects all three artifacts even when CASCADE exits
# before DatasetAnalysis can create them.
: > log.txt
: > errors.txt
printf 'NoInco; error; ; ; ; ; ; ' > result.txt

echo "Running CASCADE for $LANGUAGE with $CONFIG_FILE"

executor_args=()
test_generator_args=()

if [[ $LANGUAGE == python ]]; then
	if ! detection=$(python3 ./detect_python_version.py ./repository); then
		echo "Could not determine a Python version" |
			tee -a errors.txt >&2
		exit 2
	fi

	IFS=$'\t' read -r \
		python_version \
		detection_source \
		runtime_hint \
		python_dependencies <<< "$detection"

	python_image="python:$python_version"

	executor_args=(
		-exec "image:$python_image"
	)

	if [[ -n "$python_dependencies" ]]; then
		executor_args+=(
			-exec "dependencies:$python_dependencies"
		)
	fi

	test_generator_args=(
		-testgen "runtime_hint:$runtime_hint"
	)

	echo \
		"Selected Python $python_version ($detection_source) using $python_image"

	if [[ $runtime_hint == *"TensorFlow"* ]]; then
		echo "Test runtime: $runtime_hint"
	fi
fi

"$CASCADE_BIN" run \
	-i ./repository \
	-o . \
	-c "$CONFIG_FILE" \
	"${test_generator_args[@]}" \
	-ana debug:3 \
	"${executor_args[@]}" \
	> >(tee -a log.txt) \
	2> >(tee -a errors.txt >&2)
status=$?

# PythonTwoStepAnalysis writes the actual classification into analyzed.json.
# DatasetEvaluation expects the same value in result.txt.
if verdict=$(jq -er '
	if type == "array" then
		.[0].verdict
	else
		.verdict
	end
	| select(type == "string" and length > 0)
' analyzed.json 2>>errors.txt); then
	printf '%s' "$verdict" > result.txt
else
	echo "Could not read a verdict from analyzed.json; keeping the fallback result" \
		| tee -a errors.txt >&2
fi

if ((status != 0)); then
	echo "CASCADE exited with status $status" | tee -a errors.txt >&2
fi

exit "$status"
