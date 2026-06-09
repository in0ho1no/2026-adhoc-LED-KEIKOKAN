"""BLEキャプチャから 0x03 / 0x60 / 0x80 のシーケンスを抽出する。

nRF Sniffer の Wireshark テキスト出力を逐次読み込みし、巨大なログでも
入力全体をメモリに載せずに処理する。

抽出結果は counter 昇順で JSONL または CSV に出力する。
1レコードには次の情報を含める。

- 4バイト counter 値
- 0x03 の Advertising Data 32 バイト列
- 0x02 の 0x60 系 Advertising Data 32 バイト列
- 0x02 の 0x80 系 Advertising Data 32 バイト列
- 元のフレーム番号と時刻
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

PacketType = Literal['03', '60', '80']

_FRAME_RE = re.compile(r'^Frame\s+(\d+):')
_TIME_RE = re.compile(r'^\s*\[Time since reference or first frame:\s+(.+?)\s+seconds\]$')
_SERVICE_DATA_RE = re.compile(r'^\s+Service Data:\s+([0-9a-fA-F]+)\s*$')
_UUID_RE = re.compile(r'UUID 16: Unknown \(0x([0-9a-fA-F]{4})\)')

_PAYLOAD_03_PREFIX = '1F 02 01 06 1B 03 '
_PAYLOAD_02_PREFIX = '1F 02 01 06 03 02 50 FD 17 16 50 FD '


@dataclass(slots=True)
class RelevantPacket:
    """抽出対象の広告パケット。"""

    frame_no: int
    packet_type: PacketType
    payload: str
    counter: int | None
    time_since_first: str | None
    service_data: str = ''


@dataclass(slots=True)
class SequenceRecord:
    """0x03 / 0x60 / 0x80 の 1 組。"""

    counter_hex: str
    counter_int: int
    frame_03: int
    frame_60: int
    frame_80: int
    time_03: str | None
    time_60: str | None
    time_80: str | None
    service_data_60: str
    service_data_80: str
    payload_03: str
    payload_60: str
    payload_80: str


def _hex_pairs(hex_string: str) -> str:
    """連結された16進文字列をスペース区切りへ変換する。"""
    return ' '.join(hex_string[index : index + 2].upper() for index in range(0, len(hex_string), 2))


def _uuid_payload(uuid_values: list[str]) -> str:
    """UUID 一覧から 0x03 ペイロードを構築する。"""
    little_endian = ' '.join(f'{value[2:4].upper()} {value[0:2].upper()}' for value in uuid_values)
    return f'{_PAYLOAD_03_PREFIX}{little_endian}'


def _service_payload(service_data: str) -> str:
    """Service Data から 0x02 ペイロードを構築する。"""
    return f'{_PAYLOAD_02_PREFIX}{_hex_pairs(service_data)}'


def _parse_frame(block: list[str]) -> RelevantPacket | None:
    """1フレーム分のテキストから対象パケットを抽出する。"""
    text = ''.join(block)
    if 'CRC: Ok' not in text or 'Malformed' in text:
        return None

    frame_match = _FRAME_RE.match(block[0].strip())
    if frame_match is None:
        return None

    frame_no = int(frame_match.group(1))
    time_since_first: str | None = None
    service_data: str | None = None
    uuid_values: list[str] = []

    for line in block:
        if time_since_first is None:
            time_match = _TIME_RE.match(line)
            if time_match is not None:
                time_since_first = time_match.group(1)

        if service_data is None:
            service_match = _SERVICE_DATA_RE.match(line)
            if service_match is not None:
                service_data = service_match.group(1).upper()

        uuid_match = _UUID_RE.search(line)
        if uuid_match is not None:
            uuid_values.append(uuid_match.group(1).upper())

    if service_data is not None:
        packet_type_text = service_data[4:6]
        if packet_type_text not in {'60', '80'}:
            return None

        counter = int(service_data[6:14], 16)
        packet_type: PacketType = '60' if packet_type_text == '60' else '80'
        return RelevantPacket(
            frame_no=frame_no,
            packet_type=packet_type,
            payload=_service_payload(service_data),
            counter=counter,
            time_since_first=time_since_first,
            service_data=service_data,
        )

    if len(uuid_values) == 13:
        return RelevantPacket(
            frame_no=frame_no,
            packet_type='03',
            payload=_uuid_payload(uuid_values),
            counter=None,
            time_since_first=time_since_first,
        )

    return None


def iter_relevant_packets(input_path: Path) -> Iterator[RelevantPacket]:
    """入力ファイルを逐次読み込みし、対象パケットだけを yield する。"""
    current_block: list[str] = []

    with input_path.open(encoding='utf-8', errors='ignore') as handle:
        for line in handle:
            if line.startswith('Frame '):
                if current_block:
                    packet = _parse_frame(current_block)
                    if packet is not None:
                        yield packet
                current_block = [line]
            elif current_block:
                current_block.append(line)

    if current_block:
        packet = _parse_frame(current_block)
        if packet is not None:
            yield packet


def extract_sequences(input_path: Path) -> tuple[list[SequenceRecord], int]:
    """対象パケット列から 03 / 60 / 80 の完全な組を抽出する。"""
    pending: list[RelevantPacket] = []
    packet_count = 0
    sequences_by_counter: dict[int, SequenceRecord] = {}

    for packet in iter_relevant_packets(input_path):
        packet_count += 1
        pending.append(packet)

        while len(pending) >= 3:
            window = pending[:3]
            packet_types = {item.packet_type for item in window}
            if packet_types != {'03', '60', '80'}:
                pending.pop(0)
                continue

            packet_03 = next(item for item in window if item.packet_type == '03')
            packet_60 = next(item for item in window if item.packet_type == '60')
            packet_80 = next(item for item in window if item.packet_type == '80')

            if packet_60.counter != packet_80.counter or packet_60.counter is None:
                pending.pop(0)
                continue

            counter = packet_60.counter
            sequences_by_counter.setdefault(
                counter,
                SequenceRecord(
                    counter_hex=f'0x{counter:08X}',
                    counter_int=counter,
                    frame_03=packet_03.frame_no,
                    frame_60=packet_60.frame_no,
                    frame_80=packet_80.frame_no,
                    time_03=packet_03.time_since_first,
                    time_60=packet_60.time_since_first,
                    time_80=packet_80.time_since_first,
                    service_data_60=packet_60.service_data,
                    service_data_80=packet_80.service_data,
                    payload_03=packet_03.payload,
                    payload_60=packet_60.payload,
                    payload_80=packet_80.payload,
                ),
            )
            del pending[:3]

    sequences = sorted(sequences_by_counter.values(), key=lambda item: item.counter_int)
    return sequences, packet_count


def write_jsonl(sequences: list[SequenceRecord], output_path: Path) -> None:
    """抽出結果を JSONL で書き出す。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8', newline='') as handle:
        for sequence in sequences:
            handle.write(json.dumps(asdict(sequence), ensure_ascii=False))
            handle.write('\n')


def write_csv_file(sequences: list[SequenceRecord], output_path: Path) -> None:
    """抽出結果を CSV で書き出す。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if sequences:
        fieldnames = list(asdict(sequences[0]).keys())
    else:
        empty_record = SequenceRecord('', 0, 0, 0, 0, None, None, None, '', '', '', '', '')
        fieldnames = list(asdict(empty_record).keys())

    with output_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for sequence in sequences:
            writer.writerow(asdict(sequence))


def build_argument_parser() -> argparse.ArgumentParser:
    """コマンドライン引数パーサーを作成する。"""
    parser = argparse.ArgumentParser(description='BLE ログから 0x03 / 0x60 / 0x80 の完全な組を抽出する')
    parser.add_argument('input_path', type=Path, help='Wireshark テキスト出力ファイル')
    parser.add_argument(
        '--output',
        type=Path,
        help='出力先ファイル。省略時は入力ファイルの横に .sequences.jsonl か .sequences.csv を作成する',
    )
    parser.add_argument(
        '--format',
        choices=('jsonl', 'csv'),
        default='jsonl',
        help='出力形式。既定値は jsonl',
    )
    return parser


def main() -> None:
    """エントリーポイント。"""
    parser = build_argument_parser()
    args = parser.parse_args()
    input_path: Path = args.input_path
    output_path: Path = args.output or input_path.with_suffix(f'.sequences.{args.format}')

    if not input_path.exists():
        print(f'エラー: 入力ファイルが見つかりません: {input_path}', file=sys.stderr)
        sys.exit(1)

    sequences, packet_count = extract_sequences(input_path)
    if args.format == 'jsonl':
        write_jsonl(sequences, output_path)
    else:
        write_csv_file(sequences, output_path)

    print(f'抽出パケット数: {packet_count}')
    print(f'抽出シーケンス数: {len(sequences)}')
    if sequences:
        print(f'最小 counter: {sequences[0].counter_hex}')
        print(f'最大 counter: {sequences[-1].counter_hex}')
    print(f'出力ファイル: {output_path}')


if __name__ == '__main__':
    main()
