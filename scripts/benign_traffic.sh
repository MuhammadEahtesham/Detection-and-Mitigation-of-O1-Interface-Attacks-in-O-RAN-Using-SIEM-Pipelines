#!/bin/bash
BASE='http://localhost:8181/rests/data/network-topology:network-topology/topology=topology-netconf/node=pynts-o-du-o1/yang-ext:mount'
PATHS=("ietf-netconf-monitoring:netconf-state" "ietf-hardware:hardware" "ietf-yang-library:yang-library")
DURATION=${DURATION:-1200}
END=$((SECONDS + DURATION))
n=0

read_one() {
  local P=${PATHS[$((RANDOM % ${#PATHS[@]}))]}
  local code=$(curl -s -o /dev/null -w "%{http_code}" -u "$AUTH" "$BASE/$P")
  n=$((n + 1))
  echo "$(date +%T) #$n $P -> $code"
}

while [ $SECONDS -lt $END ]; do
  read_one

  # Occasionally an operator browses several views in quick succession
  if [ $((RANDOM % 10)) -eq 0 ]; then
    for i in $(seq $((RANDOM % 3 + 2))); do read_one; sleep 0.3; done
  fi

  # Occasional reachability check, as health monitoring would do
  if [ $((RANDOM % 20)) -eq 0 ]; then
    ping -c $((RANDOM % 3 + 1)) 172.21.0.100 > /dev/null
    echo "$(date +%T) ping"
  fi

  # Irregular pause between 0.5 and 6 seconds
  sleep $(awk -v r=$RANDOM 'BEGIN{printf "%.2f", 0.5 + (r / 32767) * 5.5}')
done

echo "done: $n requests in $DURATION seconds"
