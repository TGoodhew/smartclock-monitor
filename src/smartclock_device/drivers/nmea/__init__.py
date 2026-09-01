"""The NMEA 0183 family: a receiver that talks rather than answering.

``driver.NmeaDriver`` is the implementation and ``sentences`` is its parser. Nothing else in the
application imports either — §12's seam is that the application asks *the driver the session
selected*, and this package is one of the things that can be selected.
"""

from __future__ import annotations

from smartclock_device.drivers.nmea.driver import NmeaDriver

__all__ = ["NmeaDriver"]
