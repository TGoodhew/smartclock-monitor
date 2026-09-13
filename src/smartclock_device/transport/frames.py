"""Binary frames among the ASCII, recognised on bytes before any line splitting (#59, #63).

**Some receivers broadcast a binary time code while answering text commands on the same link.** A
Trimble UCCM-P emits a 44-byte frame every two seconds, unasked, in the middle of whatever else is
on the wire. Those bytes contain `0x0D` and `0x0A` by coincidence rather than as terminators, so a
reader that splits on line endings first shreds such a frame into fragments that are individually
meaningless — and, because §11.1 forbids raising, discards them in silence.

**Measured rather than assumed, and it is rarer than it sounds.** Across the 150 captured frames
`ResponseBuffer`'s CR-or-LF rule would have split exactly **four** — one CR and three LFs in 6,600
bytes. That is not an argument for ignoring it: one frame in thirty-seven is a time code lost every
minute or so, unpredictably. The stronger argument is the byte that appears in *every* frame — a
NUL, 3,454 of them across the corpus — which no line rule removes, so without this the status
screen's text would carry embedded NULs in every read that overlapped a broadcast.

That is the whole of it: **frame first, split what is left.** `ResponseBuffer` still does the line
work; this runs ahead of it and takes the frames out.

The delimiters are read from `tests/fixtures/uccm/frames-13sep2026.txt` — 150 frames captured over
300 s of pure listening, one every two seconds with no gaps — rather than from a datasheet. Nobody
here has a UCCM: per D7 every assertion traces to a capture or is not made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: The first byte of a time-code frame.
START: Final = 0xC5

#: The last byte of a time-code frame.
END: Final = 0xCA

#: How long one is, delimiters included. Every one of the 150 captured frames is exactly this.
LENGTH: Final = 44


@dataclass(frozen=True, slots=True)
class Framed:
    """What one pass over a byte stream separated out."""

    #: The complete frames found, in arrival order, delimiters included.
    frames: tuple[bytes, ...]

    #: Everything that was not part of a frame, in order, for the line reader to split.
    text: bytes

    #: Bytes held back because a frame may have started and not finished.
    #:
    #: **Returned rather than dropped or guessed at.** A read that ends mid-frame is the ordinary
    #: case at 57600 baud, and either discarding the tail or treating it as text would corrupt the
    #: one frame in every read that happens to straddle the boundary. The caller feeds it back in
    #: front of the next chunk.
    partial: bytes


def separate(data: bytes) -> Framed:
    """Split a chunk into complete frames and everything else.

    A `START` byte only begins a frame if a matching `END` arrives exactly `LENGTH` bytes later.
    That length check is what keeps a `0xC5` appearing inside ordinary text from swallowing the
    next 44 bytes: the candidate is rejected and the byte is text like any other.

    **Never raises** (§11.1), and never loses a byte: every input byte comes back in exactly one of
    the three fields.
    """
    frames: list[bytes] = []
    text = bytearray()
    index = 0
    end = len(data)

    while index < end:
        byte = data[index]
        if byte != START:
            text.append(byte)
            index += 1
            continue

        if index + LENGTH > end:
            # A frame may have started here and not finished arriving. Hold it back.
            return Framed(tuple(frames), bytes(text), bytes(data[index:]))

        candidate = data[index : index + LENGTH]
        if candidate[-1] == END:
            frames.append(bytes(candidate))
            index += LENGTH
            continue

        # A 0xC5 that is not the start of a frame is a byte of text like any other.
        text.append(byte)
        index += 1

    return Framed(tuple(frames), bytes(text), b"")
