#!/usr/bin/env bash
set -euo pipefail

output_dir="${FULLSEND_OUTPUT_DIR:-./output}"
failures=0

for file in topic.md evaluation.md summary.md; do
    if [[ ! -f "$output_dir/$file" ]]; then
        echo "FAIL: $output_dir/$file not found"
        failures=$((failures + 1))
    else
        echo "PASS: $output_dir/$file exists ($(wc -c < "$output_dir/$file") bytes)"
    fi
done

if [[ $failures -gt 0 ]]; then
    echo "$failures file(s) missing"
    exit 1
fi

echo "All output files present"
