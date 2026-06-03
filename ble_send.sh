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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DEVICE="${DEVICE:-0}"
DURATION="${DURATION:-0}"
REPEAT_COUNT="${REPEAT_COUNT:-1159}"
HCI_DEV="hci${DEVICE}"
STATE_FILE_BASE="${STATE_FILE_BASE:-${SCRIPT_DIR}/.ble_send_state}"
STATE_FILE_PATH=""

# ============================================================
# HCI_LE_Set_Advertising_Data パラメータ（32バイト）
#   byte[0]    : 有効データ長 = 0x1F (31)
#   byte[1-3]  : Flags AD         (02 01 06)
#   byte[4-7]  : UUID AD          (03 02 50 FD)
#   byte[8-31] : Service Data AD  (17 16 50 FD + 20バイトのペイロード)
# ============================================================

# 送信元 Random Address（OFF1回のログに合わせる）
ADV_RANDOM_ADDR="27 96 7D 51 23 DC"

# ON コマンドの 5 セット
# 0x03 の 16-bit Service Class UUIDs
ON_UUIDS_03_PAYLOADS=(
    "1F 02 01 06 1B 03 18 C6 E8 C6 E8 02 3C 13 33 B9 B7 F9 70 E1 73 6A 6C B8 A1 3B AC E8 22 1C BF 6D"
    "1F 02 01 06 1B 03 18 C6 E8 C6 E8 02 41 13 33 B9 B7 F9 70 E1 73 6A 6C B8 A1 3B AC E8 22 1C BF 86"
    "1F 02 01 06 1B 03 18 C6 E8 C6 E8 02 42 13 33 B9 B7 F9 70 E1 73 6A 6C B8 A1 3B AC E8 22 1C BF FB"
    "1F 02 01 06 1B 03 18 C6 E8 C6 E8 02 3F 13 33 B9 B7 F9 70 E1 73 6A 6C B8 A1 3B AC E8 22 1C BF 10"
    "1F 02 01 06 1B 03 18 C6 E8 C6 E8 02 40 13 33 B9 B7 F9 70 E1 73 6A 6C B8 A1 3B AC E8 22 1C BF 50"
)

# 0x02 の 60系
ON_60_PAYLOADS=(
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 02 3C D7 56 47 EF 8F 0F 9E 63 BD AE 22 DB 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 02 41 86 37 AA 07 91 A2 F7 77 95 04 19 35 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 02 42 FD 25 38 9A E3 1D 6C 82 6B 52 E4 8F 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 02 3F B9 5D 32 3C B1 F7 77 C8 18 00 92 27 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 02 40 A4 07 4E E6 A0 BC 4C EA D1 BE A0 5A 00"
)

# 0x02 の 80系
ON_80_PAYLOADS=(
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 02 3C 9E 4A 54 DB 26 99 FD 49 67 E7 66 DA 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 02 41 51 C9 17 D6 1D 58 46 9D 7C 4E 1E 87 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 02 42 32 AE D5 7E A8 FC 0D D0 B4 39 51 35 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 02 3F 58 50 EF 80 FB 4F 4E C6 9E 99 9F 50 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 02 40 EF 6A E5 F9 E4 4F E3 AB D2 8D D7 EC 00"
)

# OFF コマンドの 5 セット
# 0x03 の 16-bit Service Class UUIDs
OFF_UUIDS_03_PAYLOADS=(
    "1F 02 01 06 1B 03 18 C6 E8 C6 E8 01 F3 13 D6 8A 33 44 B0 EF 1C 4C 07 0D 9C 1A 58 94 8E 6A 52 DB"
    "1F 02 01 06 1B 03 18 C6 E8 C6 E8 02 1F 13 D6 8A 33 44 B0 EF 1C 4C 07 0D 9C 1A 58 94 8E 6A 52 C7"
    "1F 02 01 06 1B 03 18 C6 E8 C6 E8 02 20 13 D6 8A 33 44 B0 EF 1C 4C 07 0D 9C 1A 58 94 8E 6A 52 8C"
    "1F 02 01 06 1B 03 18 C6 E8 C6 E8 02 21 13 D6 8A 33 44 B0 EF 1C 4C 07 0D 9C 1A 58 94 8E 6A 52 5A"
    "1F 02 01 06 1B 03 18 C6 E8 C6 E8 02 22 13 D6 8A 33 44 B0 EF 1C 4C 07 0D 9C 1A 58 94 8E 6A 52 27"
)

# 0x02 の 60系
OFF_60_PAYLOADS=(
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 01 F3 94 47 2A C6 0B AB 49 54 94 74 04 ED 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 02 1F 01 D8 92 08 B7 AF C2 E5 FB 88 7D FE 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 02 20 2F 72 27 51 B6 6D B0 20 31 7D B1 42 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 02 21 70 06 2B 05 7D B0 F1 FE 43 C1 47 A2 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 60 00 00 02 22 1E E3 B9 FA 1E F0 6E D7 4A EA D1 92 00"
)

# 0x02 の 80系
OFF_80_PAYLOADS=(
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 01 F3 F1 FE 78 72 6D D0 EF 92 5E 82 7E 44 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 02 1F BF 1C AE E1 3D 73 2A 99 5A 65 5D EC 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 02 20 C2 D3 13 88 13 71 D4 99 1B CC 10 26 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 02 21 53 0D A7 03 70 33 B7 E2 85 B3 6C 69 00"
    "1F 02 01 06 03 02 50 FD 17 16 50 FD 40 80 80 00 00 02 22 97 3F E1 DE 24 C6 55 F4 C6 80 DB 09 00"
)

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

normalize_sequence_index() {
    local raw_value="$1"
    local sequence_length="$2"

    if [[ ! "$raw_value" =~ ^[0-9]+$ ]]; then
        raw_value=0
    fi

    echo "$((raw_value % sequence_length))"
}

load_sequence_index() {
    local state_file="$1"
    local sequence_length="$2"
    local stored_value=0

    if [[ -f "$state_file" ]]; then
        stored_value="$(<"$state_file")"
    fi

    normalize_sequence_index "$stored_value" "$sequence_length"
}

store_sequence_index() {
    local state_file="$1"
    local next_index="$2"

    printf '%s\n' "$next_index" > "$state_file"
}

select_payload_pair() {
    local command_name="$1"
    local -n out_payload_60="$2"
    local -n out_payload_80="$3"
    local -n out_payload_03="$4"
    local -n out_sequence_label="$5"

    case "$command_name" in
        on)
            local sequence_length="${#ON_60_PAYLOADS[@]}"
            local state_file="${STATE_FILE_BASE}_on.idx"
            local sequence_index
            sequence_index="$(load_sequence_index "$state_file" "$sequence_length")"
            out_payload_60="${ON_60_PAYLOADS[$sequence_index]}"
            out_payload_80="${ON_80_PAYLOADS[$sequence_index]}"
            out_payload_03="${ON_UUIDS_03_PAYLOADS[$sequence_index]}"
            out_sequence_label="$((sequence_index + 1))/${sequence_length}"
            store_sequence_index "$state_file" "$(((sequence_index + 1) % sequence_length))"
            STATE_FILE_PATH="$state_file"
            ;;
        off)
            local sequence_length="${#OFF_60_PAYLOADS[@]}"
            local state_file="${STATE_FILE_BASE}_off.idx"
            local sequence_index
            sequence_index="$(load_sequence_index "$state_file" "$sequence_length")"
            out_payload_60="${OFF_60_PAYLOADS[$sequence_index]}"
            out_payload_80="${OFF_80_PAYLOADS[$sequence_index]}"
            out_payload_03="${OFF_UUIDS_03_PAYLOADS[$sequence_index]}"
            out_sequence_label="$((sequence_index + 1))/${sequence_length}"
            store_sequence_index "$state_file" "$(((sequence_index + 1) % sequence_length))"
            STATE_FILE_PATH="$state_file"
            ;;
        *)
            echo "内部エラー: 未知のコマンドです: $command_name" >&2
            exit 1
            ;;
    esac
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

select_payload_pair "$1" payload_60 payload_80 payload_03 sequence_label

set_adv_enable 01

echo "送信開始"
echo "  選択セット: ${sequence_label}"
echo "  状態ファイル: ${STATE_FILE_PATH}"

for ((i = 1; i <= REPEAT_COUNT; i++)); do
    case $(((i - 1) % 3)) in
        0)
            set_adv_data "${payload_03}"
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
