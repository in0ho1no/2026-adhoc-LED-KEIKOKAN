"""PulseView のロジック CSV から遷移間隔ヒストグラムを集計する。

time + logic level の CSV を逐次読み込みし、各チャネルについて次を集計する。

- 反転から次の反転までの間隔
- High / Low が継続した時間

UART の bit period 候補があるか、あるいは粗いパルス列しかないかを確認する用途を想定する。
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ChannelStats:
    """1 チャネル分の集計結果。"""

    transition_intervals_ns: Counter[int]
    high_run_lengths_ns: Counter[int]
    low_run_lengths_ns: Counter[int]
    transition_count: int = 0


def build_argument_parser() -> argparse.ArgumentParser:
    """コマンドライン引数パーサーを作成する。"""
    parser = argparse.ArgumentParser(
        description='PulseView の CSV からチャネルごとの遷移間隔ヒストグラムを集計する',
    )
    parser.add_argument('input_path', type=Path, help='PulseView から export した CSV ファイル')
    parser.add_argument(
        '--top',
        type=int,
        default=12,
        help='各ヒストグラムで表示する上位件数。既定値は 12',
    )
    return parser


def _format_duration_ns(duration_ns: int) -> str:
    """ナノ秒値を見やすい文字列へ変換する。"""
    if duration_ns >= 1_000_000:
        return f'{duration_ns / 1_000_000:.3f} ms'
    if duration_ns >= 1_000:
        return f'{duration_ns / 1_000:.3f} us'
    return f'{duration_ns} ns'


def _format_baud(duration_ns: int) -> str:
    """区間長から相当するビットレートを概算する。"""
    if duration_ns <= 0:
        return '-'
    return f'{1_000_000_000 / duration_ns:,.1f} bps'


def _print_counter(title: str, counts: Counter[int], top_n: int) -> None:
    """ヒストグラム上位を標準出力へ表示する。"""
    print(title)
    if not counts:
        print('  データなし')
        return

    for duration_ns, count in counts.most_common(top_n):
        duration_text = _format_duration_ns(duration_ns)
        baud_text = _format_baud(duration_ns)
        print(f'  {duration_text:>12}  count={count:>6}  ~{baud_text}')


def analyze_logic_csv(input_path: Path) -> tuple[list[ChannelStats], int]:
    """CSV を逐次読み込みし、各チャネルの統計を返す。"""
    with input_path.open('r', encoding='utf-8', newline='') as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            msg = f'空ファイルです: {input_path}'
            raise ValueError(msg)
        if len(header) < 2:
            msg = f'列数が不足しています: {header}'
            raise ValueError(msg)

        channel_count = len(header) - 1
        stats = [
            ChannelStats(
                transition_intervals_ns=Counter(),
                high_run_lengths_ns=Counter(),
                low_run_lengths_ns=Counter(),
            )
            for _ in range(channel_count)
        ]

        previous_time_ns: int | None = None
        previous_values: list[int] | None = None
        last_transition_time_ns: list[int | None] = [None] * channel_count
        state_start_time_ns: list[int | None] = [None] * channel_count
        row_count = 0

        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(header):
                msg = f'{row_number} 行目の列数が不正です: {row}'
                raise ValueError(msg)

            try:
                time_ns = int(row[0])
                channel_values = [int(value) for value in row[1:]]
            except ValueError as error:
                msg = f'{row_number} 行目を整数として解釈できません: {row}'
                raise ValueError(msg) from error

            if previous_time_ns is not None and time_ns < previous_time_ns:
                msg = f'{row_number} 行目で時刻が逆行しています: {time_ns} < {previous_time_ns}'
                raise ValueError(msg)

            row_count += 1
            if previous_values is None:
                previous_time_ns = time_ns
                previous_values = channel_values
                state_start_time_ns = [time_ns] * channel_count
                continue

            for channel_index, (previous_value, current_value) in enumerate(
                zip(previous_values, channel_values, strict=True),
            ):
                if current_value not in {0, 1}:
                    msg = f'{row_number} 行目のチャネル値が 0/1 ではありません: {current_value}'
                    raise ValueError(msg)

                if current_value == previous_value:
                    continue

                stats[channel_index].transition_count += 1
                run_start_ns = state_start_time_ns[channel_index]
                if run_start_ns is None:
                    msg = f'{row_number} 行目でチャネル {channel_index + 1} の開始時刻を特定できません'
                    raise ValueError(msg)
                run_length_ns = time_ns - run_start_ns
                if previous_value == 1:
                    stats[channel_index].high_run_lengths_ns[run_length_ns] += 1
                else:
                    stats[channel_index].low_run_lengths_ns[run_length_ns] += 1

                transition_start_ns = last_transition_time_ns[channel_index]
                if transition_start_ns is not None:
                    stats[channel_index].transition_intervals_ns[time_ns - transition_start_ns] += 1
                last_transition_time_ns[channel_index] = time_ns
                state_start_time_ns[channel_index] = time_ns

            previous_time_ns = time_ns
            previous_values = channel_values

    return stats, row_count


def print_report(input_path: Path, stats: list[ChannelStats], row_count: int, top_n: int) -> None:
    """集計結果を表示する。"""
    print(f'入力ファイル: {input_path}')
    print(f'サンプル行数: {row_count}')
    print(f'チャネル数: {len(stats)}')

    for index, channel_stats in enumerate(stats, start=1):
        print()
        print(f'== Channel {index} ==')
        print(f'遷移回数: {channel_stats.transition_count}')
        _print_counter('遷移間隔の上位:', channel_stats.transition_intervals_ns, top_n)
        _print_counter('High 継続時間の上位:', channel_stats.high_run_lengths_ns, top_n)
        _print_counter('Low 継続時間の上位:', channel_stats.low_run_lengths_ns, top_n)


def main() -> None:
    """エントリーポイント。"""
    parser = build_argument_parser()
    args = parser.parse_args()
    input_path: Path = args.input_path

    if not input_path.exists():
        print(f'エラー: 入力ファイルが見つかりません: {input_path}', file=sys.stderr)
        sys.exit(1)

    try:
        stats, row_count = analyze_logic_csv(input_path)
    except ValueError as error:
        print(f'エラー: {error}', file=sys.stderr)
        sys.exit(1)

    print_report(input_path, stats, row_count, args.top)


if __name__ == '__main__':
    main()
