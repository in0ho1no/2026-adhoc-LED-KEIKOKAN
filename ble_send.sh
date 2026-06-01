#!/bin/bash
# BLE コマンド送信スクリプト（hcitool HCI コマンド直接送信版）
#
# Python の raw HCI ソケットの代わりに hcitool cmd で HCI コマンドを直接送信する。
#
# 使い方:
#   sudo bash ble_send.sh on
#   sudo bash ble_send.sh off
#
# 環境変数:
#   DURATION : フレーム種別あたりの送信秒数 (デフォルト: 1.5)
#   DEVICE   : HCI デバイス番号             (デフォルト: 0)

set -euo pipefail

DEVICE="${DEVICE:-0}"
DURATION="${DURATION:-1.5}"
HCI_DEV="hci${DEVICE}"

# ============================================================
# HCI_LE_Set_Advertising_Data パラメータ（32バイト）
#   byte[0]    : 有効データ長 = 0x1F (31)
#   byte[1-3]  : Flags AD         (02 01 06)
#   byte[4-7]  : UUID AD          (03 02 50 FD)
#   byte[8-31] : Service Data AD  (17 16 50 FD + 20バイトのペイロード)
# ============================================================

# ON コマンド (counter=0xf0)
ADV_ON_60="1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 01 F0 24 64 FF 13 C2 14 3A 87 1A 85 DD 5A 00"
ADV_ON_80="1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 01 F0 DB 29 1B 4A BA 46 A2 8C F4 FE 17 7F 00"

# OFF コマンド (counter=0xeb)
ADV_OFF_60="1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 01 EB 44 B3 62 C7 D9 7F FC 4C 92 A1 65 B1 00"
ADV_OFF_80="1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 01 EB 17 84 CA 38 B1 5E 24 7E C5 A7 53 77 00"

# ============================================================
# 関数
# ============================================================

check_requirements() {
    if [[ "$(id -u)" -ne 0 ]]; then
        echo "エラー: sudo で実行してください" >&2
        exit 1
    fi
    if ! command -v hcitool &>/dev/null; then
        echo "エラー: hcitool が見つかりません。sudo apt install bluez を実行してください" >&2
        exit 1
    fi
}

bring_up_hci() {
    # bluetoothd 停止後に hci デバイスが DOWN になる場合の対処
    if hciconfig "${HCI_DEV}" up 2>/dev/null; then
        return 0
    fi

    # hci0 が存在しない場合: hciuart サービスを再起動して再アタッチを試みる（RPi 4 向け）
    echo "  ${HCI_DEV} が利用不可。hciuart を再起動します..."
    systemctl start hciuart 2>/dev/null || true
    sleep 1

    if hciconfig "${HCI_DEV}" up 2>/dev/null; then
        return 0
    fi

    echo "エラー: ${HCI_DEV} を起動できません" >&2
    echo "現在のデバイス一覧:" >&2
    hciconfig -a 2>&1 >&2 || true
    return 1
}

send_frame() {
    local adv_data="$1"
    local label="$2"

    echo "  [${label}] 送信中..."

    # HCI_LE_Set_Advertising_Parameters (OGF=0x08, OCF=0x0006)
    # ADV_NONCONN_IND, interval=100ms (0x00A0), 全チャネル, パブリックアドレス
    hcitool -i "${HCI_DEV}" cmd 0x08 0x0006 \
        A0 00 A0 00 03 00 00 00 00 00 00 00 00 07 00 > /dev/null

    # HCI_LE_Set_Advertising_Data (OGF=0x08, OCF=0x0008)
    # shellcheck disable=SC2086
    hcitool -i "${HCI_DEV}" cmd 0x08 0x0008 ${adv_data} > /dev/null

    # HCI_LE_Set_Advertise_Enable: 有効化 (OGF=0x08, OCF=0x000A)
    hcitool -i "${HCI_DEV}" cmd 0x08 0x000A 01 > /dev/null

    sleep "${DURATION}"

    # HCI_LE_Set_Advertise_Enable: 無効化
    hcitool -i "${HCI_DEV}" cmd 0x08 0x000A 00 > /dev/null

    echo "  [${label}] 完了"
}

# ============================================================
# メイン
# ============================================================

if [[ "${1:-}" != "on" && "${1:-}" != "off" ]]; then
    echo "使い方: sudo bash $0 on|off" >&2
    echo "  DURATION=<秒> DEVICE=<番号> sudo bash $0 on  # 環境変数での設定も可" >&2
    exit 1
fi

check_requirements

# 終了時（正常・エラー・Ctrl+C 問わず）に Bluetooth を再起動
trap 'echo "Bluetooth サービスを再起動中..." && systemctl start bluetooth' EXIT

echo "[1/3] Bluetooth サービスを停止..."
systemctl stop bluetooth

echo "[2/3] HCI デバイスを UP にする..."
bring_up_hci

echo "[3/3] ${1^^} コマンドを送信 (各フレーム ${DURATION}s)..."
if [[ "$1" == "on" ]]; then
    send_frame "${ADV_ON_60}" "60系"
    send_frame "${ADV_ON_80}" "80系"
else
    send_frame "${ADV_OFF_60}" "60系"
    send_frame "${ADV_OFF_80}" "80系"
fi

echo "送信終了"
