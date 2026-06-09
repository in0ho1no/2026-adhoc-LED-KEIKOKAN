"""BLE Beaconキャプチャファイルのパーサー。

nRF SnifferでキャプチャしたWiresharkテキスト出力を解析し、
BLE Beaconパケット情報をCSV形式で出力する。

出力列:
    No.          : Wiresharkパケット番号
    Time         : キャプチャタイムスタンプ（秒）
    Source       : 送信元MACアドレス
    Service Data : Tuya BLEサービスデータのhexペイロード（存在しない場合は空）
    Info         : パケット種別（Malformedパケットの識別に使用）
    Length       : パケット長（バイト）
"""

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_INPUT_DIR = Path(__file__).parent / 'input'
_OUTPUT_DIR = Path(__file__).parent / 'output'


@dataclass
class BlePacket:
    """BLEパケットの解析結果。"""

    no: int
    time: float
    source: str
    service_data: str
    info: str
    length: int


def _parse_summary_line(line: str) -> tuple[int, float, str, str, int] | None:
    """サマリー行をパースして (No., Time, Source, Info, Length) を返す。

    Args:
        line: 先頭の空白をstripしたサマリー行。

    Returns:
        (No., Time, Source, Info, Length) のタプル。パースできない場合は None。
    """
    parts = line.split()
    # 最小フィールド数: No. Time Source Dest LE LL Length
    if len(parts) < 7:
        return None
    try:
        no = int(parts[0])
        time_val = float(parts[1])
        source = parts[2]
        # parts[3]: Destination, parts[4]: "LE", parts[5]: "LL", parts[6]: Length
        if parts[4] != 'LE' or parts[5] != 'LL':
            return None
        length = int(parts[6])
        info = ' '.join(parts[7:]) if len(parts) > 7 else ''
        return no, time_val, source, info, length
    except (ValueError, IndexError):
        return None


def parse_ble_capture(filepath: Path) -> list[BlePacket]:
    """BLE Beaconキャプチャファイルをパースしてパケットリストを返す。

    Args:
        filepath: nRF SnifferのWiresharkテキスト出力ファイルのパス。

    Returns:
        解析されたBLEパケットのリスト。Malformed Packet は除外済み。
    """
    packets: list[BlePacket] = []
    header_re = re.compile(r'^No\.\s+Time')
    service_data_re = re.compile(r'^\s+Service Data:\s+([0-9a-fA-F]+)\s*$')

    current_packet: BlePacket | None = None
    expect_summary = False

    with filepath.open(encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.rstrip('\n')

            if header_re.match(line):
                expect_summary = True
                continue

            if expect_summary:
                if line.strip() == '':
                    continue  # ヘッダーとサマリーの間の空行はスキップ
                expect_summary = False
                result = _parse_summary_line(line.strip())
                if result is not None:
                    if current_packet is not None:
                        packets.append(current_packet)
                    no, time_val, source, info, length = result
                    current_packet = BlePacket(
                        no=no,
                        time=time_val,
                        source=source,
                        service_data='',
                        info=info,
                        length=length,
                    )
                continue

            if current_packet is not None:
                m = service_data_re.match(line)
                if m:
                    current_packet.service_data = m.group(1)

    if current_packet is not None:
        packets.append(current_packet)

    return [p for p in packets if 'Malformed' not in p.info]


def write_csv(packets: list[BlePacket], output_path: Path) -> None:
    """パケットリストをCSVファイルに書き出す。

    Args:
        packets: 書き出すBLEパケットのリスト。
        output_path: 出力CSVファイルのパス。
    """
    with output_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['No.', 'Time', 'Source', 'Service Data', 'Info', 'Length'])
        for pkt in packets:
            writer.writerow(
                [
                    pkt.no,
                    f'{pkt.time:.6f}',
                    pkt.source,
                    pkt.service_data,
                    pkt.info,
                    pkt.length,
                ]
            )


def print_stats(packets: list[BlePacket], label: str) -> None:
    """パケット統計をコンソールに表示する。

    Args:
        packets: 統計対象のパケットリスト。
        label: 表示ラベル。
    """
    with_service_data = [p for p in packets if p.service_data]
    print(f'[{label}]')
    print(f'  総パケット数          : {len(packets)}')
    print(f'  Service Data あり     : {len(with_service_data)}')

    if with_service_data:
        # Service Data のバイト[2] (0-indexed) の分布を表示
        # Tuya BLE では このバイトがフレーム種別を示す可能性がある
        byte2_counts: dict[str, int] = {}
        for p in with_service_data:
            if len(p.service_data) >= 6:
                b2 = p.service_data[4:6]
                byte2_counts[b2] = byte2_counts.get(b2, 0) + 1
        print(f'  Service Data byte[2] : {byte2_counts}')


def main() -> None:
    """Input フォルダ内の .txt ファイルを一括パースし output フォルダへ CSV を出力する。"""
    if not _INPUT_DIR.exists():
        print(f'エラー: input フォルダが見つかりません: {_INPUT_DIR}')
        sys.exit(1)

    txt_files = sorted(_INPUT_DIR.glob('*.txt'))
    if not txt_files:
        print(f'処理対象の .txt ファイルが見つかりません: {_INPUT_DIR}')
        sys.exit(0)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for input_path in txt_files:
        output_path = _OUTPUT_DIR / input_path.with_suffix('.csv').name
        packets = parse_ble_capture(input_path)
        print_stats(packets, input_path.name)
        write_csv(packets, output_path)
        print(f'CSV出力完了: {output_path}\n')


if __name__ == '__main__':
    main()
