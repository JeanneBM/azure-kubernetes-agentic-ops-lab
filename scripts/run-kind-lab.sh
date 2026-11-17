#!/usr/bin/env bash
set -euo pipefail

workdir=$(mktemp -d)
cluster="agentic-lab-$(basename "$workdir" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')"
export KUBECONFIG="$workdir/kubeconfig"
image=nginx:1.28-alpine
started=$SECONDS

cleanup() {
  local result=$?
  trap - EXIT
  if (( result != 0 )) && [[ -s "$KUBECONFIG" ]]; then
    kubectl --request-timeout=10s describe pod lab-web >&2 || true
  fi
  if ! kind delete cluster --name "$cluster"; then
    result=1
  fi
  rm -rf -- "$workdir"
  if (( result == 0 )); then
    printf 'PASS: both scenarios, baseline restored after each, cluster deleted (%ss)\n' "$((SECONDS - started))"
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

kind create cluster --name "$cluster" --kubeconfig "$KUBECONFIG" --wait 120s
docker pull "$image"
kind load docker-image --name "$cluster" "$image"

create_pod() {
  local pod_image=$1
  local config=${2:-}
  {
    cat <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: lab-web
spec:
  automountServiceAccountToken: false
  containers:
    - name: web
      image: $pod_image
      imagePullPolicy: Never
      readinessProbe:
        httpGet:
          path: /
          port: 80
EOF
    if [[ -n "$config" ]]; then
      cat <<EOF
      envFrom:
        - configMapRef:
            name: $config
EOF
    fi
  } | kubectl --request-timeout=10s create -f -
}

remove_pod() {
  kubectl --request-timeout=60s delete pod lab-web --timeout=45s
}

baseline() {
  create_pod "$image"
  kubectl wait pod/lab-web --for=condition=Ready --timeout=90s
}

wait_for_reason() {
  local expected=$1
  local deadline=$((SECONDS + 60))
  local reason
  while (( SECONDS < deadline )); do
    reason=$(kubectl --request-timeout=10s get pod lab-web \
      -o 'jsonpath={.status.containerStatuses[0].state.waiting.reason}')
    if [[ "$reason" == "$expected" ]]; then
      return 0
    fi
    sleep 2
  done
  printf 'Expected %s, last observed %s\n' "$expected" "${reason:-none}" >&2
  return 1
}

baseline
remove_pod
create_pod nginx:lab-missing-image
wait_for_reason ErrImageNeverPull
remove_pod
baseline
printf 'PASS: invalid image blocked startup, HTTP-ready baseline restored\n'

remove_pod
create_pod "$image" lab-missing-config
wait_for_reason CreateContainerConfigError
kubectl --request-timeout=10s get pod lab-web \
  -o 'jsonpath={.status.containerStatuses[0].state.waiting.message}' \
  | grep -F 'lab-missing-config'
printf '\n'
remove_pod
baseline
printf 'PASS: missing ConfigMap blocked startup, HTTP-ready baseline restored\n'
