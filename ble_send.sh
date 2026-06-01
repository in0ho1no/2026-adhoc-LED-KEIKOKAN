#!/bin/bash
# BLE コマンド送信スクリプト
#
# 使い方:
#   sudo bash ble_send.sh on
#   sudo bash ble_send.sh off

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${SCRIPT_DIR}/.venv/bin/python"
SENDER="${SCRIPT_DIR}/src/ble_sender/send_adv.py"

# 引数チェック
if [[ "${1:-}" != "on" && "${1:-}" != "off" ]]; then
    echo "使い方: sudo bash $0 on|off" >&2
    exit 1
fi

# root チェック
if [[ "$(id -u)" -ne 0 ]]; then
    echo "エラー: sudo で実行してください" >&2
    exit 1
fi

# 仮想環境チェック
if [[ ! -x "${PYTHON}" ]]; then
    echo "エラー: 仮想環境が見つかりません。プロジェクトディレクトリで uv sync を実行してください" >&2
    exit 1
fi

# 終了時（正常・エラー・Ctrl+C を問わず）に Bluetooth を再起動
trap 'echo "Bluetooth サービスを再起動中..." && systemctl start bluetooth' EXIT

echo "[1/2] Bluetooth サービスを停止..."
systemctl stop bluetooth

echo "[2/2] ${1^^} コマンドを送信..."
"${PYTHON}" "${SENDER}" "$1"
