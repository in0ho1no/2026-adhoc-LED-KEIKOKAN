"""parse_ble_capture モジュールのテスト。"""

import csv
from pathlib import Path

import pytest

from parse_log.parse_ble_capture import BlePacket, _parse_summary_line, parse_ble_capture, write_csv

# 3パケット（正常×2、Malformed×1）を含む最小フィクスチャ
_FIXTURE_TEXT = """\
No.     Time           Source                Destination           Protocol Length Value_ary  Value      Info
   1702 3.477664       dc:23:51:7d:96:27     Broadcast             LE LL    63                           ADV_NONCONN_IND

Frame 1702: Packet, 63 bytes on wire (504 bits)
    Advertising Data
        Service Data - 16 bit UUID
            Service Data: 408060000001e70a9a673df24863673e8e927a00
    CRC: 0xf638a2

No.     Time           Source                Destination           Protocol Length Value_ary  Value      Info
   1703 3.478523       dc:23:51:7d:96:27     Broadcast             LE LL    63                           ADV_NONCONN_IND[Malformed Packet]

Frame 1703: Packet, 63 bytes on wire
[Malformed Packet: BT Common]

No.     Time           Source                Destination           Protocol Length Value_ary  Value      Info
   1704 3.479394       dc:23:51:7d:96:27     Broadcast             LE LL    63                           ADV_NONCONN_IND

Frame 1704: Packet, 63 bytes on wire (504 bits)
    Advertising Data
        Flags
            Length: 2
    CRC: 0x1dd03a
"""


class TestParseSummaryLine:
    def test_valid_line_with_info(self) -> None:
        line = '1702 3.477664 dc:23:51:7d:96:27 Broadcast LE LL 63 ADV_NONCONN_IND'
        assert _parse_summary_line(line) == (1702, 3.477664, 'dc:23:51:7d:96:27', 'ADV_NONCONN_IND', 63)

    def test_valid_line_malformed_info(self) -> None:
        line = '1703 3.478523 dc:23:51:7d:96:27 Broadcast LE LL 63 ADV_NONCONN_IND[Malformed Packet]'
        assert _parse_summary_line(line) == (1703, 3.478523, 'dc:23:51:7d:96:27', 'ADV_NONCONN_IND[Malformed Packet]', 63)

    def test_valid_line_without_info(self) -> None:
        line = '1702 3.477664 dc:23:51:7d:96:27 Broadcast LE LL 63'
        assert _parse_summary_line(line) == (1702, 3.477664, 'dc:23:51:7d:96:27', '', 63)

    def test_returns_none_for_too_short_line(self) -> None:
        assert _parse_summary_line('1702 3.477664 dc:23:51:7d:96:27') is None

    def test_returns_none_for_non_ble_protocol(self) -> None:
        assert _parse_summary_line('1702 3.477664 aa:bb:cc:dd:ee:ff Broadcast OTHER PROTO 63 INFO') is None

    def test_returns_none_for_invalid_packet_number(self) -> None:
        assert _parse_summary_line('abc 3.477664 dc:23:51:7d:96:27 Broadcast LE LL 63 INFO') is None


class TestParseBleCapture:
    @pytest.fixture
    def capture_file(self, tmp_path: Path) -> Path:
        p = tmp_path / 'test_capture.txt'
        p.write_text(_FIXTURE_TEXT, encoding='utf-8')
        return p

    def test_malformed_packets_are_excluded(self, capture_file: Path) -> None:
        packets = parse_ble_capture(capture_file)
        assert len(packets) == 2
        assert all('Malformed' not in p.info for p in packets)

    def test_packet_fields_are_correct(self, capture_file: Path) -> None:
        packets = parse_ble_capture(capture_file)
        p = packets[0]
        assert p.no == 1702
        assert p.time == pytest.approx(3.477664)
        assert p.source == 'dc:23:51:7d:96:27'
        assert p.length == 63
        assert p.info == 'ADV_NONCONN_IND'

    def test_service_data_extracted(self, capture_file: Path) -> None:
        packets = parse_ble_capture(capture_file)
        assert packets[0].service_data == '408060000001e70a9a673df24863673e8e927a00'

    def test_packet_without_service_data_has_empty_string(self, capture_file: Path) -> None:
        packets = parse_ble_capture(capture_file)
        assert packets[1].service_data == ''

    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        empty_file = tmp_path / 'empty.txt'
        empty_file.write_text('', encoding='utf-8')
        assert parse_ble_capture(empty_file) == []


class TestWriteCsv:
    def test_csv_has_correct_header(self, tmp_path: Path) -> None:
        out = tmp_path / 'out.csv'
        write_csv([], out)
        with out.open(encoding='utf-8') as f:
            header = next(csv.reader(f))
        assert header == ['No.', 'Time', 'Source', 'Service Data', 'Info', 'Length']

    def test_csv_contains_packet_data(self, tmp_path: Path) -> None:
        out = tmp_path / 'out.csv'
        packets = [
            BlePacket(no=1702, time=3.477664, source='dc:23:51:7d:96:27', service_data='408060', info='ADV_NONCONN_IND', length=63),
        ]
        write_csv(packets, out)
        with out.open(encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        assert rows[0]['No.'] == '1702'
        assert rows[0]['Source'] == 'dc:23:51:7d:96:27'
        assert rows[0]['Service Data'] == '408060'

    def test_time_is_formatted_with_6_decimal_places(self, tmp_path: Path) -> None:
        out = tmp_path / 'out.csv'
        packets = [
            BlePacket(no=1, time=3.5, source='aa:bb:cc:dd:ee:ff', service_data='', info='INFO', length=63),
        ]
        write_csv(packets, out)
        with out.open(encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        assert rows[0]['Time'] == '3.500000'

    def test_empty_packets_produces_header_only(self, tmp_path: Path) -> None:
        out = tmp_path / 'out.csv'
        write_csv([], out)
        with out.open(encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        assert rows == []
