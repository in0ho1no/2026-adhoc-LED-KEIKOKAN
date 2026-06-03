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
#   DURATION : 1回の広告データ更新後の待ち時間 (デフォルト: 0)
#   REPEAT_COUNT : 総送信回数 (デフォルト: 1159)
#   DEVICE   : HCI デバイス番号             (デフォルト: 0)

set -euo pipefail

DEVICE="${DEVICE:-0}"
DURATION="${DURATION:-0}"
REPEAT_COUNT="${REPEAT_COUNT:-1159}"
HCI_DEV="hci${DEVICE}"

# ============================================================
# HCI_LE_Set_Advertising_Data パラメータ（32バイト）
#   byte[0]    : 有効データ長 = 0x1F (31)
#   byte[1-3]  : Flags AD         (02 01 06)
#   byte[4-7]  : UUID AD          (03 02 50 FD)
#   byte[8-31] : Service Data AD  (17 16 50 FD + 20バイトのペイロード)
# ============================================================

# 0x03 の 16-bit Service Class UUIDs（OFF1回のログで観測された UUID 列）
ADV_UUIDS_03="1F 02 01 06 1B 03 18 C6 E8 C6 E8 01 F3 13 D6 8A 33 44 B0 EF 1C 4C 07 0D 9C 1A 58 94 8E 6A 52 DB"

# 送信元 Random Address（OFF1回のログに合わせる）
ADV_RANDOM_ADDR="27 96 7D 51 23 DC"

# ON コマンド (counter=0xf0)
ADV_ON_60="1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 01 F0 24 64 FF 13 C2 14 3A 87 1A 85 DD 5A 00"
ADV_ON_80="1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 01 F0 DB 29 1B 4A BA 46 A2 8C F4 FE 17 7F 00"

# OFF コマンド (counter=0xF3)
ADV_OFF_60="1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 01 F3 94 47 2A C6 0B AB 49 54 94 74 04 ED 00"
ADV_OFF_80="1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 01 F3 F1 FE 78 72 6D D0 EF 92 5E 82 7E 44 00"

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

set_adv_data() {
    local adv_data="$1"

    # HCI_LE_Set_Advertising_Data (OGF=0x08, OCF=0x0008)
    # shellcheck disable=SC2086
    hcitool -i "${HCI_DEV}" cmd 0x08 0x0008 ${adv_data} > /dev/null
}

set_adv_enable() {
    local enable_flag="$1"

    # HCI_LE_Set_Advertise_Enable (OGF=0x08, OCF=0x000A)
    hcitool -i "${HCI_DEV}" cmd 0x08 0x000A "${enable_flag}" > /dev/null
}

set_random_address() {
    # HCI_LE_Set_Random_Address (OGF=0x08, OCF=0x0005)
    hcitool -i "${HCI_DEV}" cmd 0x08 0x0005 ${ADV_RANDOM_ADDR} > /dev/null
}

set_adv_params() {
    # HCI_LE_Set_Advertising_Parameters (OGF=0x08, OCF=0x0006)
    # ADV_NONCONN_IND, interval=100ms (0x00A0), 全チャネル, Random Address
    hcitool -i "${HCI_DEV}" cmd 0x08 0x0006 \
        A0 00 A0 00 03 01 00 00 00 00 00 00 00 07 00 > /dev/null
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

trap 'set_adv_enable 00 >/dev/null 2>&1 || true; systemctl start bluetooth >/dev/null 2>&1 || true' EXIT

systemctl stop bluetooth
bring_up_hci

set_random_address

set_adv_params

if [[ "$1" == "on" ]]; then
    payload_60="${ADV_ON_60}"
    payload_80="${ADV_ON_80}"
else
    payload_60="${ADV_OFF_60}"
    payload_80="${ADV_OFF_80}"
fi

set_adv_enable 01

echo "送信開始"

for ((i = 1; i <= REPEAT_COUNT; i++)); do
    case $(((i - 1) % 3)) in
        0)
            set_adv_data "${ADV_UUIDS_03}"
            ;;
        1)
            set_adv_data "${payload_60}"
            ;;
        2)
            set_adv_data "${payload_80}"
            ;;
    esac

    sleep "${DURATION}"
done

set_adv_enable 00

echo "送信終了"
