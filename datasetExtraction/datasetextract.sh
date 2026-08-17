#!/usr/bin/env bash

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASCADE_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

INDEX_FILE="$SCRIPT_DIR/index.csv"
WORK_DIR="$SCRIPT_DIR/work"
CONFIG_DIR="$CASCADE_ROOT/configs/datasetExtraction"
CASCADE_BIN="$CASCADE_ROOT/../cascade.venv/bin/CASCADE"
REPOSITORY_CACHE=""
GITHUB_BASE_URL="https://github.com"
LANGUAGE_FILTER="all"
LIMIT=0
MODE=""
KEEP_EXTRACTED=false
OVERWRITE=false

usage() {
    cat <<'EOF'
Usage:
  ./datasetextract.sh --dry-run [options]
  ./datasetextract.sh --execute [options]

Modes:
  --dry-run             Validate index.csv and print the extraction plan.
  --execute             Clone/check out repositories and run CASCADE extraction.

Options:
  --language LANGUAGE   Process python, java, rust, csharp, or all (default).
  --index FILE          CSV input file. Default: datasetExtraction/index.csv
  --workdir DIRECTORY   Extraction root. Default: datasetExtraction/work
  --config-dir DIR      Extraction config directory.
                        Default: configs/datasetExtraction
  --cascade-bin FILE    CASCADE executable.
                        Default: ../cascade.venv/bin/CASCADE
  --repo-cache DIR      Repository cache. Default: WORKDIR/repositories
  --github-base URL     Git hosting base URL. Default: https://github.com
  --keep-extracted      Keep extracted.json after successful extraction.
  --overwrite           Re-run existing cases and replace extraction outputs.
                        Patch and container-hook files are left untouched.
  --limit NUMBER        Stop after NUMBER valid cases. Default: no limit.
  -h, --help            Show this help.

Expected CSV columns:
  language,repository,commit,case_number,function_name,file_path,inconsistent[,project_path]

project_path is optional. It is relative to the repository and identifies a
project root or, for C#, a solution file. If omitted, the script searches
upward from file_path for the nearest language-specific project marker.

Existing successful cases are resumed by default. With --overwrite, generated
extraction files are replaced while patch and container-hook files are kept.
EOF
}

die() {
    echo "Error: $*" >&2
    exit 2
}

normalize_language() {
    case "${1,,}" in
        python|py)
            printf 'python'
            ;;
        java)
            printf 'java'
            ;;
        rust|rs)
            printf 'rust'
            ;;
        csharp|c#|cs)
            printf 'csharp'
            ;;
        *)
            return 1
            ;;
    esac
}

config_for_language() {
    case "$1" in
        python)
            printf '%s/Python.json' "$CONFIG_DIR"
            ;;
        java)
            printf '%s/Java.json' "$CONFIG_DIR"
            ;;
        rust)
            printf '%s/Rust.json' "$CONFIG_DIR"
            ;;
        csharp)
            printf '%s/CSharp.json' "$CONFIG_DIR"
            ;;
        *)
            return 1
            ;;
    esac
}

strip_cr() {
    printf '%s' "${1//$'\r'/}"
}

is_valid_analyzed_file() {
    local analyzed_file=$1
    [[ -s "$analyzed_file" ]] || return 1

    if command -v jq >/dev/null 2>&1; then
        jq -e 'type == "array" and length == 1' "$analyzed_file" >/dev/null 2>&1
    else
        return 0
    fi
}

record_failure() {
    local language=$1
    local repository=$2
    local commit=$3
    local case_number=$4
    local reason=$5

    printf '%s,%s,%s,%s,%s\n' \
        "$language" "$repository" "$commit" "$case_number" "$reason" \
        >> "$FAILED_FILE"
}

ensure_repository() {
    local repository=$1
    local commit=$2
    local repository_dir=$3
    local clone_url="${GITHUB_BASE_URL%/}/${repository}.git"

    if [[ ! -d "$repository_dir/.git" ]]; then
        mkdir -p "$(dirname "$repository_dir")"
        echo "  cloning $clone_url"
        git clone --quiet "$clone_url" "$repository_dir" || return 1
    fi

    if ! git -C "$repository_dir" cat-file -e "${commit}^{commit}" 2>/dev/null; then
        echo "  fetching commit $commit"
        git -C "$repository_dir" fetch --quiet origin "$commit" || {
            git -C "$repository_dir" fetch --quiet --tags origin || return 1
        }
    fi

    git -C "$repository_dir" cat-file -e "${commit}^{commit}" 2>/dev/null ||
        return 1
    git -C "$repository_dir" checkout --quiet --detach --force "$commit" ||
        return 1
}

find_marker_upwards() {
    local start_dir=$1
    local repository_dir=$2
    shift 2

    local current_dir=$start_dir
    while [[ $current_dir == "$repository_dir" || $current_dir == "$repository_dir/"* ]]; do
        local marker
        for marker in "$@"; do
            if [[ -e "$current_dir/$marker" ]]; then
                printf '%s' "$current_dir"
                return 0
            fi
        done
        [[ $current_dir != "$repository_dir" ]] || break
        current_dir=$(dirname "$current_dir")
    done
    return 1
}

find_csharp_solution() {
    local start_dir=$1
    local repository_dir=$2

    local current_dir=$start_dir
    while [[ $current_dir == "$repository_dir" || $current_dir == "$repository_dir/"* ]]; do
        local solution
        solution=$(
            find "$current_dir" -maxdepth 1 -type f \
                \( -name '*.sln' -o -name '*.slnx' \) \
                -print 2>/dev/null |
                sort |
                head -n 1
        )
        if [[ -n "$solution" ]]; then
            printf '%s' "$solution"
            return 0
        fi
        [[ $current_dir != "$repository_dir" ]] || break
        current_dir=$(dirname "$current_dir")
    done
    return 1
}

resolve_input_path() {
    local language=$1
    local repository_dir=$2
    local file_path=$3
    local project_path=$4

    local normalized_file=${file_path//\\//}
    normalized_file=${normalized_file#./}
    local absolute_file="$repository_dir/$normalized_file"
    local start_dir
    start_dir=$(dirname "$absolute_file")

    local input_path=""
    if [[ -n "$project_path" ]]; then
        local normalized_project=${project_path//\\//}
        normalized_project=${normalized_project#./}
        input_path="$repository_dir/$normalized_project"
        [[ -e "$input_path" ]] || return 1
    else
        case "$language" in
            python)
                if [[ -e "$repository_dir/pyproject.toml" ||
                    -e "$repository_dir/setup.py" ||
                    -e "$repository_dir/setup.cfg" ]]; then
                    input_path="$repository_dir"
                else
                    input_path=$(
                        find_marker_upwards \
                            "$start_dir" "$repository_dir" \
                            pyproject.toml setup.py setup.cfg
                    ) || input_path="$repository_dir"
                fi
                ;;
            java)
                input_path=$(
                    find_marker_upwards \
                        "$start_dir" "$repository_dir" \
                        pom.xml build.gradle build.gradle.kts settings.gradle settings.gradle.kts
                ) || input_path="$repository_dir"
                ;;
            rust)
                input_path=$(
                    find_marker_upwards \
                        "$start_dir" "$repository_dir" \
                        Cargo.toml
                ) || input_path="$repository_dir"
                ;;
            csharp)
                input_path=$(find_csharp_solution "$start_dir" "$repository_dir") ||
                    return 1
                ;;
            *)
                return 1
                ;;
        esac
    fi

    local input_base=$input_path
    [[ -d "$input_base" ]] || input_base=$(dirname "$input_base")

    RESOLVED_INPUT_PATH=$input_path
    RESOLVED_FILE_PATH=$(
        realpath --canonicalize-missing --relative-to="$input_base" "$absolute_file"
    ) || return 1
}

clear_extraction_outputs() {
    local output_dir=$1

    # Remove only generated extraction artifacts. Do not remove file.patch,
    # container_patch.sh, patch.sh, or other manually maintained files.
    rm -f \
        "$output_dir/analyzed.json" \
        "$output_dir/extracted.json" \
        "$output_dir/extraction.log" \
        "$output_dir/errors.txt" \
        "$output_dir/inconsistent_functions.json" \
        "$output_dir/inconsistency.txt"
}

execute_case() {
    local language=$1
    local repository=$2
    local commit=$3
    local case_number=$4
    local function_name=$5
    local file_path=$6
    local inconsistent=$7
    local config_file=$8
    local output_dir=$9
    local project_path=${10}

    local repository_dir="$REPOSITORY_CACHE/$repository"
    local run_log="$output_dir/extraction.log"

    if ! $OVERWRITE && is_valid_analyzed_file "$output_dir/analyzed.json"; then
        printf '%s\n' "$inconsistent" > "$output_dir/inconsistency.txt"
        echo "RESUME $language $repository $commit/$case_number"
        ((resumed_count += 1))
        return 0
    fi

    echo "RUN    $language $repository $commit/$case_number"
    echo "       $file_path :: $function_name"

    if ! ensure_repository "$repository" "$commit" "$repository_dir"; then
        echo "  ERROR: repository checkout failed" >&2
        record_failure "$language" "$repository" "$commit" "$case_number" "checkout"
        ((failed_count += 1))
        return 1
    fi

    if ! resolve_input_path \
        "$language" "$repository_dir" "$file_path" "$project_path"; then
        echo "  ERROR: project input path could not be resolved" >&2
        record_failure \
            "$language" "$repository" "$commit" "$case_number" \
            "input_resolution"
        ((failed_count += 1))
        return 1
    fi

    echo "  input: $RESOLVED_INPUT_PATH"
    echo "  file:  $RESOLVED_FILE_PATH"

    if $OVERWRITE && [[ -d "$output_dir" ]]; then
        echo "  overwriting generated extraction files"
        clear_extraction_outputs "$output_dir"
    fi

    mkdir -p "$output_dir"
    printf '%s\n' "$inconsistent" > "$output_dir/inconsistency.txt"

    local signature_function_name=$function_name
    if [[ $language == "python" ]]; then
        signature_function_name=${function_name##*.}
    fi

    local command=(
        "$CASCADE_BIN" run
        -i "$RESOLVED_INPUT_PATH"
        -o "$output_dir"
        -c "$config_file"
        --filters "(0,expected:$signature_function_name)"
        --filters "(1,expected:$RESOLVED_FILE_PATH)"
    )

    if [[ $language == "python" ]]; then
        command+=(--filters "(2,expected:$function_name)")
    fi

    printf 'Command:' > "$run_log"
    printf ' %q' "${command[@]}" >> "$run_log"
    printf '\n\n' >> "$run_log"

    "${command[@]}" 2>&1 | tee -a "$run_log"
    local cascade_status=${PIPESTATUS[0]}

    if ((cascade_status != 0)); then
        echo "  ERROR: CASCADE exited with status $cascade_status" >&2
        record_failure \
            "$language" "$repository" "$commit" "$case_number" \
            "cascade_exit_$cascade_status"
        ((failed_count += 1))
        return 1
    fi

    if ! is_valid_analyzed_file "$output_dir/analyzed.json"; then
        echo "  ERROR: no non-empty analyzed.json was produced" >&2
        record_failure "$language" "$repository" "$commit" "$case_number" "no_match"
        ((failed_count += 1))
        return 1
    fi

    local match_count="unknown"
    if command -v jq >/dev/null 2>&1; then
        match_count=$(jq 'length' "$output_dir/analyzed.json")
    fi
    if [[ $match_count != "unknown" && $match_count -ne 1 ]]; then
        echo "  ERROR: filters selected $match_count functions instead of one" >&2
        record_failure \
            "$language" "$repository" "$commit" "$case_number" \
            "filter_count_$match_count"
        ((failed_count += 1))
        return 1
    fi

    if ! $KEEP_EXTRACTED; then
        rm -f "$output_dir/extracted.json"
    fi

    echo "  OK: $output_dir/analyzed.json"
    ((executed_count += 1))
    return 0
}

while (($# > 0)); do
    case "$1" in
        --dry-run)
            [[ -z "$MODE" ]] || die "choose exactly one mode"
            MODE="dry-run"
            shift
            ;;
        --execute)
            [[ -z "$MODE" ]] || die "choose exactly one mode"
            MODE="execute"
            shift
            ;;
        --language)
            (($# >= 2)) || die "--language requires a value"
            LANGUAGE_FILTER=$2
            shift 2
            ;;
        --index)
            (($# >= 2)) || die "--index requires a file"
            INDEX_FILE=$2
            shift 2
            ;;
        --workdir)
            (($# >= 2)) || die "--workdir requires a directory"
            WORK_DIR=$2
            shift 2
            ;;
        --config-dir)
            (($# >= 2)) || die "--config-dir requires a directory"
            CONFIG_DIR=$2
            shift 2
            ;;
        --cascade-bin)
            (($# >= 2)) || die "--cascade-bin requires a file"
            CASCADE_BIN=$2
            shift 2
            ;;
        --repo-cache)
            (($# >= 2)) || die "--repo-cache requires a directory"
            REPOSITORY_CACHE=$2
            shift 2
            ;;
        --github-base)
            (($# >= 2)) || die "--github-base requires a URL or path"
            GITHUB_BASE_URL=$2
            shift 2
            ;;
        --keep-extracted)
            KEEP_EXTRACTED=true
            shift
            ;;
        --overwrite)
            OVERWRITE=true
            shift
            ;;
        --limit)
            (($# >= 2)) || die "--limit requires a number"
            [[ $2 =~ ^[0-9]+$ ]] ||
                die "--limit must be a non-negative integer"
            LIMIT=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

[[ -n "$MODE" ]] || die "choose --dry-run or --execute"
[[ -f "$INDEX_FILE" ]] || die "index file not found: $INDEX_FILE"

if [[ $LANGUAGE_FILTER != "all" ]]; then
    LANGUAGE_FILTER=$(normalize_language "$LANGUAGE_FILTER") ||
        die "unsupported language: $LANGUAGE_FILTER"
fi

if [[ -z "$REPOSITORY_CACHE" ]]; then
    REPOSITORY_CACHE="$WORK_DIR/repositories"
fi

if [[ $MODE == "execute" ]]; then
    command -v git >/dev/null 2>&1 || die "git is required"
    [[ -x "$CASCADE_BIN" ]] || die "CASCADE executable not found: $CASCADE_BIN"
    mkdir -p "$WORK_DIR"
fi

FAILED_FILE="$WORK_DIR/failed.csv"
if [[ $MODE == "execute" ]]; then
    printf 'language,repository,commit,case_number,reason\n' > "$FAILED_FILE"
fi

declare -A SEEN_CASES=()

line_number=0
valid_count=0
skipped_count=0
unsupported_count=0
duplicate_count=0
executed_count=0
resumed_count=0
failed_count=0

if [[ $MODE == "dry-run" ]]; then
    printf 'language\trepository\tcommit\tcase\tfunction\tfile\tlabel\tproject\tconfig\toutput\n'
fi

while IFS=, read -r raw_language raw_repository raw_commit raw_case_number \
    raw_function_name raw_file_path raw_inconsistent raw_project_path \
    extra_columns; do
    ((line_number += 1))

    language=$(strip_cr "$raw_language")
    repository=$(strip_cr "$raw_repository")
    commit=$(strip_cr "$raw_commit")
    case_number=$(strip_cr "$raw_case_number")
    function_name=$(strip_cr "$raw_function_name")
    file_path=$(strip_cr "$raw_file_path")
    inconsistent=$(strip_cr "$raw_inconsistent")
    project_path=$(strip_cr "${raw_project_path:-}")
    extra_columns=$(strip_cr "${extra_columns:-}")

    [[ -n "$language$repository$commit$case_number$function_name$file_path$inconsistent" ]] ||
        continue
    [[ $language == \#* ]] && continue
    [[ ${language,,} == "language" ]] && continue

    if ! normalized_language=$(normalize_language "$language"); then
        echo "SKIP line $line_number: unsupported language '$language'" >&2
        ((unsupported_count += 1))
        continue
    fi
    language=$normalized_language

    if [[ $LANGUAGE_FILTER != "all" && $language != "$LANGUAGE_FILTER" ]]; then
        continue
    fi

    missing=()
    [[ -n "$repository" ]] || missing+=(repository)
    [[ -n "$commit" ]] || missing+=(commit)
    [[ -n "$case_number" ]] || missing+=(case_number)
    [[ -n "$function_name" ]] || missing+=(function_name)
    [[ -n "$file_path" ]] || missing+=(file_path)
    [[ -n "$inconsistent" ]] || missing+=(inconsistent)

    if ((${#missing[@]} > 0)); then
        echo "SKIP line $line_number: missing ${missing[*]}" >&2
        ((skipped_count += 1))
        continue
    fi

    if [[ ! $repository =~ ^[^/]+/[^/]+$ ]]; then
        echo "SKIP line $line_number: repository must use owner/name format ('$repository')" >&2
        ((skipped_count += 1))
        continue
    fi

    if [[ -n "$extra_columns" ]]; then
        echo "SKIP line $line_number: more than eight CSV columns" >&2
        ((skipped_count += 1))
        continue
    fi

    if [[ $inconsistent != "True" && $inconsistent != "False" ]]; then
        echo "SKIP line $line_number: label must be True or False" >&2
        ((skipped_count += 1))
        continue
    fi

    if [[ ! $case_number =~ ^[1-9][0-9]*$ ]]; then
        echo "SKIP line $line_number: invalid case number '$case_number'" >&2
        ((skipped_count += 1))
        continue
    fi

    config_file=$(config_for_language "$language") ||
        die "no configuration mapping for language: $language"
    if [[ ! -f "$config_file" ]]; then
        echo "SKIP line $line_number: config not found: $config_file" >&2
        ((skipped_count += 1))
        continue
    fi

    case_key="$language|$repository|$commit|$case_number"
    if [[ -n ${SEEN_CASES[$case_key]+present} ]]; then
        echo "SKIP line $line_number: duplicate case $case_key" >&2
        ((duplicate_count += 1))
        continue
    fi
    SEEN_CASES[$case_key]=1

    output_dir="$WORK_DIR/dataset/$language/$repository/$commit/$case_number"

    if [[ $MODE == "dry-run" ]]; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$language" \
            "$repository" \
            "$commit" \
            "$case_number" \
            "$function_name" \
            "$file_path" \
            "$inconsistent" \
            "${project_path:-auto}" \
            "$config_file" \
            "$output_dir"
    else
        execute_case \
            "$language" \
            "$repository" \
            "$commit" \
            "$case_number" \
            "$function_name" \
            "$file_path" \
            "$inconsistent" \
            "$config_file" \
            "$output_dir" \
            "$project_path" || true
    fi

    ((valid_count += 1))
    if ((LIMIT > 0 && valid_count >= LIMIT)); then
        break
    fi
done < "$INDEX_FILE"

echo >&2
if [[ $MODE == "dry-run" ]]; then
    echo "Dry-run summary" >&2
else
    echo "Extraction summary" >&2
fi
echo "  valid cases:        $valid_count" >&2
echo "  incomplete/invalid: $skipped_count" >&2
echo "  unsupported:        $unsupported_count" >&2
echo "  duplicates:         $duplicate_count" >&2

if [[ $MODE == "execute" ]]; then
    echo "  extracted:          $executed_count" >&2
    echo "  resumed:            $resumed_count" >&2
    echo "  failed:             $failed_count" >&2
    echo "  failure report:     $FAILED_FILE" >&2
    ((failed_count == 0))
fi
