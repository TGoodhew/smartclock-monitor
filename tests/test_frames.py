"""Binary frames among the ASCII, against the 150 the receiver actually sent.

`tests/fixtures/uccm/frames-13sep2026.txt` is 300 s of pure listening to a Trimble UCCM-P: one
44-byte time-code frame every two seconds, 149 consecutive steps of the counter, no gaps. It is
the oracle for `transport/frames.py`, and per D7 it is somebody else's receiver — nobody here has
a UCCM, so every assertion below traces to that capture rather than to a datasheet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from smartclock_device.transport.frames import END, LENGTH, START, separate

CAPTURES: Final = Path(__file__).parent / "fixtures" / "uccm"


def captured_frames() -> tuple[bytes, ...]:
    """The 150 frames, decoded from the hex the capture records them as."""
    found = []
    for raw in (CAPTURES / "frames-13sep2026.txt").read_text(encoding="ascii").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        found.append(bytes.fromhex(line.replace(" ", "")))
    return tuple(found)


def test_the_capture_is_the_shape_its_note_claims() -> None:
    """150 frames, every one 44 bytes, every one C5…CA. Asserted before anything relies on it."""
    frames = captured_frames()

    assert len(frames) == 150
    assert {len(f) for f in frames} == {LENGTH}
    assert {f[0] for f in frames} == {START}
    assert {f[-1] for f in frames} == {END}


def test_every_captured_frame_is_recovered_from_one_stream() -> None:
    """Concatenated back to back — which is what 300 s of listening put on the wire."""
    frames = captured_frames()

    separated = separate(b"".join(frames))

    assert separated.frames == frames
    assert separated.text == b""
    assert separated.partial == b""


def test_frames_are_recovered_from_between_the_text() -> None:
    """The case that matters: a receiver answering a command while broadcasting.

    Upstream's captures show the frame landing *after* the prompt rather than tidily between
    lines, so the text on either side is deliberately not whole lines.
    """
    frames = captured_frames()
    stream = b"UCCM-P >\r\n" + frames[0] + b"Command comp" + frames[1] + b"lete\r\n"

    separated = separate(stream)

    assert separated.frames == (frames[0], frames[1])
    assert separated.text == b"UCCM-P >\r\nCommand complete\r\n"


def test_a_frame_carrying_line_endings_is_not_split_on_them() -> None:
    """Why this exists at all — and the rate is measured rather than assumed.

    `ResponseBuffer` splits on CR **or** LF, and exactly four of the 150 captured frames carry one:
    three LFs and one CR in 6,600 bytes. One frame in thirty-seven is a time code lost every minute
    or so, unpredictably, which is the hard kind of defect to chase.
    """
    frames = captured_frames()
    carrying = [f for f in frames if b"\r" in f or b"\n" in f]

    assert len(carrying) == 4, "the capture's line-ending content has changed"

    separated = separate(b"".join(carrying))

    assert separated.frames == tuple(carrying)
    assert separated.text == b"", "a line reader would have shredded these into fragments"


def test_every_frame_carries_a_nul_that_no_line_rule_would_remove() -> None:
    """The stronger argument for framing, and the one that applies to all 150 rather than four.

    3,454 NUL bytes across the corpus. They break no line, so without this pass they would end up
    *inside* the text a status screen is parsed from, in every read that overlapped a broadcast.
    """
    frames = captured_frames()

    assert all(b"\x00" in f for f in frames)

    separated = separate(b"before" + b"".join(frames) + b"after")

    assert b"\x00" not in separated.text, "a NUL reached the text the line reader will split"
    assert separated.text == b"beforeafter"


def test_a_read_that_ends_mid_frame_holds_the_tail_back() -> None:
    """The ordinary case at 57600 baud, and the one where dropping or guessing corrupts a frame."""
    frame = captured_frames()[0]
    head, tail = frame[:20], frame[20:]

    first = separate(b"text" + head)
    assert first.frames == ()
    assert first.text == b"text"
    assert first.partial == head

    second = separate(first.partial + tail + b"more")
    assert second.frames == (frame,)
    assert second.text == b"more"
    assert second.partial == b""


def test_a_start_byte_in_ordinary_text_is_just_text() -> None:
    """A `0xC5` with no matching end 44 bytes later must not swallow what follows.

    Without the length check this would eat the next 43 bytes of a status screen in silence,
    which is a worse failure than the one this module exists to fix.
    """
    stream = bytes([START]) + b"this is not a frame, it is forty-odd bytes of ordinary text\r\n"

    separated = separate(stream)

    assert separated.frames == ()
    assert separated.text == stream
    assert separated.partial == b""


@pytest.mark.parametrize(
    "stream",
    [b"", b"\x00", b"plain text", bytes([START]), bytes([END]), bytes([START, END]) * 30],
)
def test_no_byte_is_ever_lost(stream: bytes) -> None:
    """§11.1's rule restated for a byte reader: it never raises, and it never eats anything."""
    separated = separate(stream)

    recovered = len(b"".join(separated.frames)) + len(separated.text) + len(separated.partial)
    assert recovered == len(stream), "every input byte must come back in exactly one of the three"


# ---- The buffer runs it ahead of line splitting -------------------------------------------------


def test_the_buffer_keeps_frames_out_of_the_text_when_asked() -> None:
    """End to end through `ResponseBuffer`, which is what actually reads a port."""
    from smartclock_device.transport.response_buffer import ResponseBuffer

    frame = captured_frames()[0]
    buffer = ResponseBuffer(detect_prompt=False, separate_frames=True)

    buffer.feed(b"first line\r\n" + frame + b"second line\r\n")

    assert buffer.drain_lines() == ("first line", "second line")
    assert buffer.drain_frames() == (frame,)


def test_the_buffer_leaves_frames_alone_unless_asked() -> None:
    """Off by default, and that default is the point.

    Every other family pays nothing for this — no scan, and no chance of a `0xC5` in ordinary text
    being examined at all. A SmartClock status screen must read exactly as it always has.

    The assertion here is about *contamination* rather than splitting, and the first draft got that
    wrong: 146 of the 150 frames carry no line ending at all, so unframed they do not break the
    text into more lines — they end up **inside** one, NULs and all. That is the quieter failure of
    the two, and the one that would reach a status-screen parser looking like data.
    """
    from smartclock_device.transport.response_buffer import ResponseBuffer

    frame = captured_frames()[0]
    assert b"\r" not in frame and b"\n" not in frame, "this frame should not split anything"
    buffer = ResponseBuffer(detect_prompt=False)

    buffer.feed(b"first line\r\n" + frame + b"second line\r\n")

    assert buffer.drain_frames() == ()
    contaminated = [line for line in buffer.drain_lines() if "\x00" in line]
    assert contaminated, "unframed, the frame's NULs end up inside a line of text"


def test_unframed_a_frame_with_a_line_ending_really_does_split_the_text() -> None:
    """The louder failure, on the four frames in 150 that carry one."""
    from smartclock_device.transport.response_buffer import ResponseBuffer

    splitting = next(f for f in captured_frames() if b"\r" in f or b"\n" in f)
    buffer = ResponseBuffer(detect_prompt=False)

    buffer.feed(b"first line\r\n" + splitting + b"second line\r\n")

    assert len(buffer.drain_lines()) > 2, "the frame's own bytes broke the text into more lines"


def test_a_frame_split_across_two_reads_survives_the_boundary() -> None:
    """At 57600 baud a read ending mid-frame is ordinary, not exceptional."""
    from smartclock_device.transport.response_buffer import ResponseBuffer

    frame = captured_frames()[0]
    buffer = ResponseBuffer(detect_prompt=False, separate_frames=True)

    buffer.feed(b"line\r\n" + frame[:19])
    assert buffer.drain_frames() == (), "nothing complete yet"

    buffer.feed(frame[19:] + b"after\r\n")

    assert buffer.drain_frames() == (frame,)
    assert buffer.drain_lines() == ("line", "after")
