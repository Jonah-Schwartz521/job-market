#!/bin/bash
for t in "$@"; do
  r=$(curl -s -w "%{http_code}" -o /tmp/lv.json \
      "https://api.lever.co/v0/postings/$t?mode=json")
  if [ "$r" = "200" ]; then
    n=$(python3 -c "import json;d=json.load(open('/tmp/lv.json'));print(len(d) if isinstance(d,list) else 0)" 2>/dev/null)
    echo "OK    $t  ($n postings)"
  else
    echo "FAIL  $t  ($r)"
  fi
  sleep 1
done
