#!/usr/bin/env bash
# Run every query in eval/queries.txt through cli.py (one-shot mode).
# Booking queries that pause for HITL approval receive a piped "y".
set -u
cd "$(dirname "$0")/.."

PY=./.venv/bin/python
OUT=logs/full_queries_run.log
: > "$OUT"

i=0
while IFS= read -r line || [[ -n "$line" ]]; do
  # skip blank lines and section comments
  [[ -z "${line// }" ]] && continue
  [[ "$line" == \#* ]] && continue
  i=$((i + 1))
  thread="qrun-$i"
  echo "" >> "$OUT"
  echo "=================== QUERY $i: $line" >> "$OUT"
  yes y 2>/dev/null | timeout 300 $PY cli.py "$thread" "$line" >> "$OUT" 2>&1
  code=$?
  if [[ $code -eq 0 ]]; then
    echo "--- QUERY $i OK" >> "$OUT"
  else
    echo "--- QUERY $i EXIT=$code" >> "$OUT"
  fi
done < eval/queries.txt

echo "ALL DONE ($i queries). Results in $OUT"
