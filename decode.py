"""
BEAN/MPX Protocol Decoder

Usage:
    python (or python3 on some Macs) decode_bean.py [file.csv]
    python decode_bean.py [file.csv] --invert
    python decode_bean.py [file.csv] --verbose        # all messages
    python decode_bean.py [file.csv] --verbose 5      # message #5 only
"""

import csv, os, sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

LONG_LOW_MIN_US  = 600.0
BIT_WIDTH_US     = 100.0
EOM_MIN_US       = 600.0
NOISE_MAX_US     =  10.0   # pulses <= this are noise; absorb into neighbours
WAKEUP_MIN_US    =  60.0   # HIGH after long LOW must be >= this to be a valid wakeup
MIN_PULSE_US     =  70.0   # minimum pulse to count as data within a message

# ── CRC-8 table — Toyota BEAN ────────────────────────────────────────────────
_CRC_TABLE = [
    0x00,0x13,0x26,0x35,0x4C,0x5F,0x6A,0x79,0x98,0x8B,0xBE,0xAD,0xD4,0xC7,0xF2,0xE1,
    0x23,0x30,0x05,0x16,0x6F,0x7C,0x49,0x5A,0xBB,0xA8,0x9D,0x8E,0xF7,0xE4,0xD1,0xC2,
    0x46,0x55,0x60,0x73,0x0A,0x19,0x2C,0x3F,0xDE,0xCD,0xF8,0xEB,0x92,0x81,0xB4,0xA7,
    0x65,0x76,0x43,0x50,0x29,0x3A,0x0F,0x1C,0xFD,0xEE,0xDB,0xC8,0xB1,0xA2,0x97,0x84,
    0x8C,0x9F,0xAA,0xB9,0xC0,0xD3,0xE6,0xF5,0x14,0x07,0x32,0x21,0x58,0x4B,0x7E,0x6D,
    0xAF,0xBC,0x89,0x9A,0xE3,0xF0,0xC5,0xD6,0x37,0x24,0x11,0x02,0x7B,0x68,0x5D,0x4E,
    0xCA,0xD9,0xEC,0xFF,0x86,0x95,0xA0,0xB3,0x52,0x41,0x74,0x67,0x1E,0x0D,0x38,0x2B,
    0xE9,0xFA,0xCF,0xDC,0xA5,0xB6,0x83,0x90,0x71,0x62,0x57,0x44,0x3D,0x2E,0x1B,0x08,
    0x0B,0x18,0x2D,0x3E,0x47,0x54,0x61,0x72,0x93,0x80,0xB5,0xA6,0xDF,0xCC,0xF9,0xEA,
    0x28,0x3B,0x0E,0x1D,0x64,0x77,0x42,0x51,0xB0,0xA3,0x96,0x85,0xFC,0xEF,0xDA,0xC9,
    0x4D,0x5E,0x6B,0x78,0x01,0x12,0x27,0x34,0xD5,0xC6,0xF3,0xE0,0x99,0x8A,0xBF,0xAC,
    0x6E,0x7D,0x48,0x5B,0x22,0x31,0x04,0x17,0xF6,0xE5,0xD0,0xC3,0xBA,0xA9,0x9C,0x8F,
    0x87,0x94,0xA1,0xB2,0xCB,0xD8,0xED,0xFE,0x1F,0x0C,0x39,0x2A,0x53,0x40,0x75,0x66,
    0xA4,0xB7,0x82,0x91,0xE8,0xFB,0xCE,0xDD,0x3C,0x2F,0x1A,0x09,0x70,0x63,0x56,0x45,
    0xC1,0xD2,0xE7,0xF4,0x8D,0x9E,0xAB,0xB8,0x59,0x4A,0x7F,0x6C,0x15,0x06,0x33,0x20,
    0xE2,0xF1,0xC4,0xD7,0xAE,0xBD,0x88,0x9B,0x7A,0x69,0x5C,0x4F,0x36,0x25,0x10,0x03,
]

def crc8(data: list) -> int:
    crc = 0
    for b in data:
        crc = _CRC_TABLE[crc ^ (b & 0xFF)]
    return crc


@dataclass
class Message:
    timestamp : float
    priority  : int
    length    : int
    did       : int
    sid       : int
    mid       : int
    payload   : List[int]
    crc       : Optional[int]
    crc_ok    : bool = False
    raw_bits  : List[int] = field(default_factory=list)


def load_pulses(path: str, invert: bool = False) -> List[Tuple[float, int, float]]:
    rows = []
    with open(path, newline='') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) >= 2:
                lvl = int(float(row[1]))
                if invert:
                    lvl = 1 - lvl
                rows.append((float(row[0]), lvl))

    # Build raw pulse list
    raw = []
    for i in range(len(rows) - 1):
        t0, lvl = rows[i]
        t1, _   = rows[i + 1]
        raw.append((t0, lvl, (t1 - t0) * 1e6))
    if rows:
        raw.append((rows[-1][0], rows[-1][1], 1e9))

    # Merge noise pulses (<= NOISE_MAX_US) into their neighbours.
    # A noise pulse is absorbed: its duration is added to the accumulated
    # duration of the previous pulse, and the following pulse (if same level
    # as previous) is also merged into that accumulated total.
    pulses = []
    i = 0
    while i < len(raw):
        t0, lvl, dur = raw[i]
        if dur <= NOISE_MAX_US and pulses:
            # Absorb noise: add its duration to the previous pulse
            pt, plvl, pdur = pulses[-1]
            accumulated = pdur + dur
            i += 1
            # Merge any following pulses that match the previous level
            while i < len(raw) and raw[i][1] == plvl:
                accumulated += raw[i][2]
                i += 1
            pulses[-1] = (pt, plvl, accumulated)
        else:
            pulses.append((t0, lvl, dur))
            i += 1

    print(f"\n[{len(pulses)}]")
    return pulses


def parse_messages(pulses, verbose_num=None):
    """
    verbose_num: None = no verbose, 0 = all messages, N = only message #N
    """
    messages = []
    i = 0
    n = len(pulses)
    msg_count = 0

    while i < n:
        t0, lvl, dur = pulses[i]

        # Wait for long LOW
        if not (lvl == 0 and dur >= LONG_LOW_MIN_US):
            i += 1
            continue

        msg_ts = t0
        i += 1
        msg_count += 1
        verbose = (verbose_num == 0 or verbose_num == msg_count)

        if verbose:
            print(f"\n[{msg_ts:.6f}] Long LOW ({dur:.0f}us) — new message")

        # Wakeup HIGH: must be >= 90us, discard first bit, keep remainder as data 1s
        if i >= n: break
        _, lvl_w, dur_w = pulses[i]
        if lvl_w != 1 or dur_w < WAKEUP_MIN_US:
            if verbose:
                print(f"  {'HIGH' if lvl_w else 'LOW'} {dur_w:.1f}us — not a valid wakeup, skipping message")
            continue
        i += 1
        wakeup_count = max(1, round(dur_w / BIT_WIDTH_US))
        kept_w = wakeup_count - 1
        if kept_w > 0:
            raw_bits = [1] * kept_w
            if verbose:
                print(f"  Wakeup HIGH {dur_w:.1f}us — first bit discarded, {kept_w} bit(s) kept: {'1' * kept_w}")
        else:
            raw_bits = []
            if verbose:
                print(f"  Wakeup HIGH {dur_w:.1f}us — discarded")

        # First LOW: use as LOW reference, keep as data bit 0
        if i >= n: break
        _, lvl_l, dur_l = pulses[i]
        if lvl_l != 0:
            continue
        i += 1
        if verbose:
            print(f"  First LOW {dur_l:.1f}us — data bit: 0")

        raw_bits.append(0)
        consecutive = 1

        while i < n:
            t_p, lvl_p, dur_p = pulses[i]

            # Reject pulses shorter than 80us
            if dur_p < MIN_PULSE_US:
                if verbose:
                    print(f"  {'HIGH' if lvl_p else 'LOW ':>5} {dur_p:7.1f}us — rejected (< {MIN_PULSE_US:.0f}us)")
                i += 1
                continue

            # Next long LOW = next message
            if lvl_p == 0 and dur_p >= LONG_LOW_MIN_US:
                break

            # EOM: HIGH >= 600us
            if lvl_p == 1 and dur_p >= EOM_MIN_US:
                if verbose:
                    print(f"  EOM: HIGH {dur_p:.1f}us — end of message")
                i += 1
                # Consume trailing tail
                while i < n:
                    _, lvl_t, dur_t = pulses[i]
                    if lvl_t == 0 and dur_t >= LONG_LOW_MIN_US:
                        break
                    i += 1
                break

            # Pack bit check: opposite value after a run of exactly 5
            if consecutive == 5 and lvl_p != raw_bits[-1]:
                count = max(1, round(dur_p / BIT_WIDTH_US))
                kept = count - 1
                if kept > 0:
                    raw_bits.extend([lvl_p] * kept)
                    if verbose:
                        print(f"  {'HIGH' if lvl_p else 'LOW ':>5} {dur_p:7.1f}us — PACK BIT discarded, {kept} bit(s) kept: {''.join([str(lvl_p)] * kept)}")
                    consecutive = count
                else:
                    if verbose:
                        print(f"  {'HIGH' if lvl_p else 'LOW ':>5} {dur_p:7.1f}us — PACK BIT discarded")
                    consecutive = 0
                i += 1
                continue

            # Normal data pulse
            count = max(1, round(dur_p / BIT_WIDTH_US))
            raw_bits.extend([lvl_p] * count)

            if verbose:
                print(f"  {'HIGH' if lvl_p else 'LOW ':>5} {dur_p:7.1f}us "
                      f"→ {count} bit(s): {''.join([str(lvl_p)] * count)}")

            # Track consecutive run
            if lvl_p == raw_bits[-count - 1] if len(raw_bits) > count else False:
                consecutive += count
            else:
                consecutive = count
            if consecutive > 5:
                consecutive = 5

            i += 1

        if verbose:
            # Build byte list for display
            padded = raw_bits[:]
            while len(padded) % 8:
                padded.append(0)
            byte_list = []
            for b in range(len(padded) // 8):
                val = 0
                for bit in padded[b * 8 : b * 8 + 8]:
                    val = (val << 1) | bit
                byte_list.append(val)
            print(f"  Bits ({len(raw_bits)}): {''.join(str(b) for b in raw_bits)}")
            print(f"  Bytes: {[hex(b) for b in byte_list]}")

        if len(raw_bits) < 8:
            continue

        # Bits -> bytes MSB-first
        padded = raw_bits[:]
        while len(padded) % 8:
            padded.append(0)
        byte_list = []
        for b in range(len(padded) // 8):
            val = 0
            for bit in padded[b * 8 : b * 8 + 8]:
                val = (val << 1) | bit
            byte_list.append(val)

        priority = (byte_list[0] >> 4) & 0x0F
        length   =  byte_list[0]       & 0x0F
        data     = byte_list[1 : 1 + length]
        crc      = byte_list[1 + length] if len(byte_list) > 1 + length else None
        crc_calc = crc8(byte_list[:1 + length])
        crc_ok   = (crc is not None) and (crc_calc == crc)
        did      = data[0] if len(data) > 0 else None
        sid      = data[1] if len(data) > 1 else None
        mid      = data[2] if len(data) > 2 else None
        payload  = data[3:] if len(data) > 3 else []

        messages.append(Message(
            timestamp = msg_ts,
            priority  = priority,
            length    = length,
            did       = did,
            sid       = sid,
            mid       = mid,
            payload   = payload,
            crc       = crc,
            crc_ok    = crc_ok,
            raw_bits  = raw_bits,
        ))

    return messages


def print_messages(msgs):
    if not msgs:
        print("No messages decoded.")
        return
    W = 88
    print(f"\n{'='*W}")
    print(f"  {len(msgs)} message(s) decoded")
    print(f"{'='*W}")
    print(f"{'#':<4} {'Time[s]':<13} {'Pri':>3} {'Len':>4}  {'DID':>6}  {'SID':>6}  {'MID':>6}  {'Payload (hex)':<24} {'CRC':>6}")
    print('-' * W)
    for idx, m in enumerate(msgs, 1):
        did_str     = f'0x{m.did:02X}' if m.did is not None else '—'
        sid_str     = f'0x{m.sid:02X}' if m.sid is not None else '—'
        mid_str     = f'0x{m.mid:02X}' if m.mid is not None else '—'
        payload_hex = ' '.join(f'{b:02X}' for b in m.payload) if m.payload else '—'
        crc_str     = f'0x{m.crc:02X} {"OK" if m.crc_ok else "FAIL"}' if m.crc is not None else 'n/a'
        print(f"{idx:<4} {m.timestamp:<13.6f} {m.priority:>3} {m.length:>4}  "
              f"{did_str:>6}  {sid_str:>6}  {mid_str:>6}  {payload_hex:<24} {crc_str:>9}")
    print('=' * W)
    print()


def main():
    args = sys.argv[1:]

    invert_flag = False
    if '--invert' in args:
        invert_flag = True
        args.remove('--invert')

    verbose_num = None
    if '--verbose' in args:
        idx = args.index('--verbose')
        if idx + 1 < len(args) and args[idx + 1].isdigit():
            verbose_num = int(args[idx + 1])
            args.pop(idx + 1)
        else:
            verbose_num = 0  # 0 = all messages
        args.pop(args.index('--verbose'))

    path = args[0] if args else 'digital.csv'

    pulses = load_pulses(path, invert=invert_flag)
    msgs   = parse_messages(pulses, verbose_num=verbose_num)

    # Single message verbose: only print the verbose trace, nothing else
    if verbose_num and verbose_num > 0:
        if verbose_num > len(msgs):
            print(f"No message #{verbose_num} (only {len(msgs)} decoded)")
        return

    print_messages(msgs)

    base     = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            base + '_decoded.csv')
    with open(out_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['#', 'Time_s', 'Priority', 'Length', 'DID', 'SID', 'MID', 'Payload_Hex', 'CRC', 'CRC_OK'])
        for idx, m in enumerate(msgs, 1):
            w.writerow([idx, f'{m.timestamp:.6f}', m.priority, m.length,
                        f'0x{m.did:02X}' if m.did is not None else '',
                        f'0x{m.sid:02X}' if m.sid is not None else '',
                        f'0x{m.mid:02X}' if m.mid is not None else '',
                        ' '.join(f'{b:02X}' for b in m.payload),
                        f'0x{m.crc:02X}' if m.crc is not None else '',
                        'OK' if m.crc_ok else 'FAIL'])
    print(f"Output: {out_path}")


if __name__ == '__main__':
    main()