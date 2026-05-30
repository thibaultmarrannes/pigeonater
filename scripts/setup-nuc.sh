#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/setup-nuc.sh [--apply] [--mode prod|dev]

Detects the host audio mode, writes .env, and prints the correct docker compose
command. With --apply, it also runs pull/up for the selected mode.

Examples:
  scripts/setup-nuc.sh
  scripts/setup-nuc.sh --apply
  scripts/setup-nuc.sh --mode dev --apply
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

repo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "${script_dir}/.."
  pwd
}

existing_env_value() {
  local key="$1"
  local file="$2"
  if [[ ! -f "$file" ]]; then
    return 1
  fi
  local line
  line="$(grep -E "^${key}=" "$file" | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    return 1
  fi
  printf '%s\n' "${line#*=}"
}

detect_pulse_socket() {
  if [[ -n "${PULSE_SOCKET_PATH:-}" && -S "${PULSE_SOCKET_PATH}" ]]; then
    printf '%s\n' "${PULSE_SOCKET_PATH}"
    return 0
  fi

  if [[ -n "${XDG_RUNTIME_DIR:-}" && -S "${XDG_RUNTIME_DIR}/pulse/native" ]]; then
    printf '%s\n' "${XDG_RUNTIME_DIR}/pulse/native"
    return 0
  fi

  local candidate
  for candidate in /run/user/*/pulse/native; do
    if [[ -S "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

detect_alsa() {
  if [[ -d /dev/snd ]]; then
    return 0
  fi
  if command -v aplay >/dev/null 2>&1 && aplay -l >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

write_env_file() {
  local file="$1"
  local model_name="$2"
  local webhook_url="$3"
  local pulse_socket="$4"

  cat >"$file" <<EOF
MODEL_NAME=${model_name}
ACTION_WEBHOOK_URL=${webhook_url}
PULSE_SOCKET_PATH=${pulse_socket}
EOF
}

main() {
  local apply=0
  local mode="prod"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --apply)
        apply=1
        shift
        ;;
      --mode)
        if [[ $# -lt 2 ]]; then
          usage
          exit 1
        fi
        mode="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage
        exit 1
        ;;
    esac
  done

  if [[ "$mode" != "prod" && "$mode" != "dev" ]]; then
    echo "Invalid mode: $mode" >&2
    exit 1
  fi

  require_command docker
  require_command git

  local root
  root="$(repo_root)"
  cd "$root"

  local env_file="${root}/.env"
  local existing_model
  existing_model="$(existing_env_value MODEL_NAME "$env_file" || true)"
  local existing_webhook
  existing_webhook="$(existing_env_value ACTION_WEBHOOK_URL "$env_file" || true)"

  local model_name="${existing_model:-yolo11n.pt}"
  local webhook_url="${existing_webhook:-}"
  local pulse_socket=""
  local audio_mode="none"
  local compose_files=()

  if pulse_socket="$(detect_pulse_socket)"; then
    audio_mode="pulse"
  elif detect_alsa; then
    audio_mode="alsa"
  fi

  write_env_file "$env_file" "$model_name" "$webhook_url" "$pulse_socket"

  if [[ "$mode" == "prod" ]]; then
    compose_files=(-f docker-compose.prod.yml)
  else
    compose_files=(-f docker-compose.yml)
  fi

  if [[ "$audio_mode" == "pulse" ]]; then
    compose_files+=(-f docker-compose.pulse.yml)
  fi

  local compose_args=(docker compose)
  local compose_cmd="docker compose"
  local file
  for file in "${compose_files[@]}"; do
    compose_args+=("$file")
    compose_cmd+=" ${file}"
  done

  echo "Repository: $root"
  echo "Mode: $mode"
  echo "Detected audio mode: $audio_mode"
  if [[ "$audio_mode" == "pulse" ]]; then
    echo "Pulse socket: $pulse_socket"
  fi
  echo ".env updated at: $env_file"
  echo
  echo "Compose command:"
  echo "  ${compose_cmd}"
  echo

  if [[ $apply -eq 1 ]]; then
    echo "Running deployment:"
    echo "  ${compose_cmd} pull"
    "${compose_args[@]}" pull
    echo "  ${compose_cmd} up -d"
    "${compose_args[@]}" up -d
    echo
    echo "Deployment complete."
  else
    echo "Next step:"
    echo "  ${compose_cmd} up -d"
  fi
}

main "$@"
