"""§10.12's auto-detect walk: try each serial setting until a receiver answers.

**The walk listens before it asks.** ``DeviceSession.open`` absorbs the power-up banner first and
parses an identity out of it, so a receiver that announces itself is recognised without a question
being sent. ``*IDN?`` follows only because a sibling model may say nothing — which is also why a
combination at the wrong rate costs the probe timeout rather than nothing.

**Every combination costs about the same, and the order is therefore the whole design.** §7.1's
note on the sequence records what getting it wrong cost: an even-parity spelling with no source
behind it sat where odd belonged, so a Z3801A was found on the last attempt of eight rather than
the second — around fourteen extra seconds.

**Cancellation is checked between combinations, not inside one.** A half-open serial port left
behind by an abandoned probe is a port the next attempt cannot have, so each attempt is allowed to
finish and close itself.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta

from smartclock_device.clock import Clock
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.drivers.registry import Registry
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.transport import timeouts
from smartclock_device.transport.base import Transport
from smartclock_device.transport.faults import TransportError
from smartclock_device.transport.settings import AUTO_DETECT_SEQUENCE, SerialSettings
from smartclock_monitor.services.session import DeviceSession

#: Builds a transport for one candidate. Injected so the walk can be tested with fakes — it is the
#: *ordering* and the give-up behaviour that are worth asserting, and neither needs a serial port.
TransportFactory = Callable[[str, SerialSettings], Transport]

#: Called before each attempt, with the candidate and how far through the sequence it is.
Progress = Callable[[SerialSettings, int, int], None]


@dataclass(frozen=True, slots=True)
class Detected:
    """What the walk found."""

    settings: SerialSettings
    session: DeviceSession
    identity: DeviceIdentity | None

    #: How many combinations were tried, including this one. Reported because "found on the first"
    #: and "found on the eighth" are the difference between a working default and a lucky guess.
    attempts: int


class DetectionCancelledError(Exception):
    """The walk was asked to stop.

    Not a failure — the user changed their mind — but an exception rather than a return value so
    it cannot be mistaken for "nothing answered", which is a different thing to tell them.
    """


async def detect(
    port: str,
    driver: ReceiverDriver,
    clock: Clock,
    build: TransportFactory,
    *,
    sequence: Sequence[SerialSettings] = AUTO_DETECT_SEQUENCE,
    probe: timedelta = timeouts.AUTO_DETECT_PROBE,
    on_progress: Progress | None = None,
    should_cancel: Callable[[], bool] | None = None,
    registry: Registry | None = None,
) -> Detected | None:
    """Walk the sequence and return the first combination a receiver answers on.

    ``None`` where nothing answered anywhere — which is a different outcome from a port that would
    not open at all, and the caller says something different about each.

    Raises :class:`DetectionCancelledError` if ``should_cancel`` says so between attempts.
    """
    for index, settings in enumerate(sequence, start=1):
        if should_cancel is not None and should_cancel():
            raise DetectionCancelledError

        if on_progress is not None:
            on_progress(settings, index, len(sequence))

        session = DeviceSession(build(port, settings), driver, clock, registry=registry)
        try:
            await session.open(probe=probe)
        except TransportError:
            # The port itself is unavailable — busy, gone, or not ours to open. Every remaining
            # combination would fail the same way, so stopping is honest and seven probe timeouts
            # faster than proving it.
            await _quietly_close(session)
            raise
        except Exception:
            # Anything else is this *combination* failing, not the port. A wrong baud rate
            # produces framing noise that can fail in a variety of ways, and none of them is a
            # reason to abandon the walk with six candidates left untried.
            await _quietly_close(session)
            continue

        if session.identity is not None:
            return Detected(
                settings=settings, session=session, identity=session.identity, attempts=index
            )

        # It opened and said nothing recognisable. That is the ordinary case for every wrong
        # combination, so close it and carry on rather than treating silence as success.
        await _quietly_close(session)

    return None


async def _quietly_close(session: DeviceSession) -> None:
    """Close, and never let closing be the reason the walk stops.

    A port that failed to open cleanly may fail to close cleanly too, and the next combination
    needs the attempt to end either way.
    """
    try:
        await session.close()
    except Exception:
        return


async def open_with(
    port: str,
    settings: SerialSettings,
    driver: ReceiverDriver,
    clock: Clock,
    build: TransportFactory,
    *,
    probe: timedelta = timeouts.AUTO_DETECT_PROBE,
    registry: Registry | None = None,
) -> DeviceSession:
    """Open one known combination, without walking.

    The manual path. It does **not** fall back to the walk on failure: a user who has picked a
    setting is asserting something about their hardware, and quietly trying seven others would
    make the picker a suggestion.
    """
    session = DeviceSession(build(port, settings), driver, clock, registry=registry)
    await session.open(probe=probe)
    return session
