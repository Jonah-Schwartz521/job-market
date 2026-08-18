#!/bin/bash
for t in "$@"; do
  r=$(curl -s -w "%{http_code}" -o /tmp/gh.json \
      "https://boards-api.greenhouse.io/v1/boards/$t/jobs")
  if [ "$r" = "200" ]; then
    n=$(python3 -c "import json;print(len(json.load(open('/tmp/gh.json'))['jobs']))" 2>/dev/null)
    echo "OK    $t  ($n jobs)"
  else
    echo "FAIL  $t  ($r)"
  fi
  sleep 1
done
