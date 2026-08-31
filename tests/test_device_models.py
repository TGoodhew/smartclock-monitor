"""The device models that are not the status screen's: identity, profile, cable, format, subsystem.

These are the pieces §10.7, §10.9 and §8.6 are built out of. None of them sees a captured screen —
they decode single answers, or they are tables — so they are tested against the strings the manuals
and the bench sittings recorded, and against the shapes §11.1 says must degrade rather than raise.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from smartclock_device.models import antenna_cable, model_profile, self_test_subsystem
from smartclock_device.models import time_code_format as tcf
from smartclock_device.models.antenna_cable import AntennaCable
from smartclock_device.models.device_identity import DeviceIdentity, ReceiverModel
from smartclock_device.models.diagnostic_log_entry import DiagnosticLogEntry
from smartclock_device.models.time_code_format import TimeCodeFormat

# ---- The antenna cable --------------------------------------------------------------------


def test_the_two_guide_cables_carry_the_guide_s_figures() -> None:
    """58503A guide, page 2-12: 1.54 ns/ft is 5.05 ns/m, and 1.2 ns/ft is 3.94 ns/m."""
    assert antenna_cable.RG213.delay_ns_per_metre == 5.05
    assert antenna_cable.BELDEN_9913.delay_ns_per_metre == 3.94


def test_lmr400_at_twenty_metres_meets_p0_11() -> None:
    """P0-11's acceptance criterion: 78.7 ns ± 0.5."""
    delay = antenna_cable.LMR400.delay_for(20)

    assert delay is not None
    assert abs(delay - 78.7) <= 0.5


def test_the_presets_lead_with_the_two_section_10_7_lists() -> None:
    assert antenna_cable.PRESETS[:2] == (antenna_cable.RG213, antenna_cable.LMR400)


@pytest.mark.parametrize("metres", [-1.0, -0.0001, math.nan, math.inf, -math.inf])
def test_a_nonsense_length_has_no_delay(metres: float) -> None:
    """``None`` rather than a negative or NaN delay: the field is fed from a text box."""
    assert antenna_cable.LMR400.delay_for(metres) is None


def test_zero_metres_is_zero_not_none() -> None:
    """A zero-length run is a legitimate answer, not a rejected one."""
    assert antenna_cable.LMR400.delay_for(0) == 0


def test_a_velocity_factor_becomes_a_cable() -> None:
    """3.3356 / 0.85 is 3.92, which is why LMR-400's published 3.93 is the sanity check on it."""
    cable = antenna_cable.from_velocity_factor(0.85)

    assert cable is not None
    assert cable.delay_ns_per_metre == pytest.approx(3.924, abs=0.001)
    assert cable.name == "Custom, velocity factor 0.85"


@pytest.mark.parametrize("factor", [0.0, 1.0, -0.5, 1.5, math.nan])
def test_a_velocity_factor_outside_the_open_unit_interval_is_no_cable(factor: float) -> None:
    """A user halfway through typing "0." has not made an error worth raising over."""
    assert antenna_cable.from_velocity_factor(factor) is None


@pytest.mark.parametrize(
    ("nanoseconds", "acceptable"),
    [
        (0.0, True),
        (78.6, True),
        (999_999.0, True),
        (-0.1, False),
        (1_000_000.0, False),
        (math.nan, False),
        (math.inf, False),
        (None, False),
    ],
)
def test_the_delay_range_matches_gps_ref_adel(nanoseconds: float | None, acceptable: bool) -> None:
    """§10.7 gives the field 0 – 999 999 ns, and §10.6's rule is to reject client-side."""
    assert antenna_cable.is_acceptable_delay(nanoseconds) is acceptable


def test_a_cable_is_frozen() -> None:
    with pytest.raises(AttributeError):
        antenna_cable.LMR400.delay_ns_per_metre = 1.0  # type: ignore[misc]


def test_a_custom_cable_is_still_a_cable() -> None:
    assert isinstance(antenna_cable.from_velocity_factor(0.66), AntennaCable)


# ---- The time code format -----------------------------------------------------------------


@pytest.mark.parametrize("answer", ["F1", "T1", "f1", " t1", ' "F1" ', "F1  "])
def test_both_spellings_of_the_first_format_are_accepted(answer: str) -> None:
    """The command's parameter is ``F1``; the message header is ``T1``. Same format."""
    assert tcf.parse(answer) == TimeCodeFormat.T1


@pytest.mark.parametrize("answer", ["F2", "T2", " f2", '"T2"'])
def test_both_spellings_of_the_second_format_are_accepted(answer: str) -> None:
    """The bench Z3805A answers ``F2``, against a manual that documents T1 as the default."""
    assert tcf.parse(answer) == TimeCodeFormat.T2


@pytest.mark.parametrize("answer", [None, "", "   ", "F3", "T0", "nonsense", "1", '""'])
def test_an_unreadable_format_is_unknown_rather_than_a_guess(answer: str | None) -> None:
    """§11.1: the receiver is in *some* format and this did not establish which."""
    assert tcf.parse(answer) == TimeCodeFormat.UNKNOWN


@pytest.mark.parametrize(
    ("code_format", "length"),
    [(TimeCodeFormat.T1, 19), (TimeCodeFormat.T2, 23), (TimeCodeFormat.UNKNOWN, None)],
)
def test_message_length_is_known_only_for_a_known_format(
    code_format: TimeCodeFormat, length: int | None
) -> None:
    assert tcf.message_length(code_format) == length


# ---- The identity -------------------------------------------------------------------------


def test_the_live_receiver_s_idn_parses() -> None:
    """Confirmed against the bench unit."""
    identity = DeviceIdentity.parse("SYMMETRICOM,Z3805A,3625A02931,1.01.03-A")

    assert identity is not None
    assert identity.manufacturer == "SYMMETRICOM"
    assert identity.model == "Z3805A"
    assert identity.serial_number == "3625A02931"
    assert identity.firmware_revision == "1.01.03-A"
    assert identity.receiver == ReceiverModel.Z3805A


def test_the_leading_space_and_field_padding_are_trimmed() -> None:
    """Every response arrives with a leading space; it is framing, not data."""
    identity = DeviceIdentity.parse(" SYMMETRICOM , Z3805A , 3625A02931 , 1.01.03-A ")

    assert identity is not None
    assert identity.manufacturer == "SYMMETRICOM"
    assert identity.serial_number == "3625A02931"


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("Z3805A", ReceiverModel.Z3805A),
        ("z3805a", ReceiverModel.Z3805A),
        ("Z3805", ReceiverModel.Z3805A),
        ("Z3801A", ReceiverModel.Z3801A),
        ("Z3816A", ReceiverModel.Z3816A),
        ("58503A", ReceiverModel.HP58503),
        ("58503B", ReceiverModel.HP58503),
        ("HP 58503B", ReceiverModel.HP58503),
        ("59551A", ReceiverModel.HP59551),
        ("Z9999X", ReceiverModel.UNKNOWN),
        ("", ReceiverModel.UNKNOWN),
    ],
)
def test_the_model_field_maps_onto_the_family(model: str, expected: ReceiverModel) -> None:
    """Prefix matching: a 58503B takes the same profile as a 58503A."""
    identity = DeviceIdentity.parse(f"SYMMETRICOM,{model},3625A02931,1.01.03-A")

    assert identity is not None
    assert identity.receiver == expected


@pytest.mark.parametrize(
    "response",
    [None, "", "   ", "SYMMETRICOM", "SYMMETRICOM,Z3805A", "A,B,C,D,E", "-113,Undefined header"],
)
def test_an_idn_in_an_unexpected_shape_is_none_rather_than_a_raise(response: str | None) -> None:
    """§11.1. The caller keeps the raw string, so nothing is lost by failing to parse."""
    assert DeviceIdentity.parse(response) is None


# ---- The model profile --------------------------------------------------------------------


def test_an_unrecognised_model_gets_everything_switched_off() -> None:
    """§8.5: absent unless shown to be present. The failure mode is a missing feature, not a
    command sent to hardware that may not have it."""
    assert model_profile.CONSERVATIVE.has_second_serial_port is False
    assert model_profile.CONSERVATIVE.has_programmable_pulse_output is False
    assert model_profile.CONSERVATIVE.has_timestamp_memory is False
    assert model_profile.CONSERVATIVE.has_pps_edge_control is False
    assert model_profile.for_model(ReceiverModel.UNKNOWN) == model_profile.CONSERVATIVE


def test_the_59551a_is_the_one_with_the_extra_hardware() -> None:
    """§8.6 lists all four as 59551A-only."""
    profile = model_profile.for_model(ReceiverModel.HP59551)

    assert profile.has_second_serial_port
    assert profile.has_programmable_pulse_output
    assert profile.has_timestamp_memory
    assert profile.has_pps_edge_control


@pytest.mark.parametrize(
    "model",
    [ReceiverModel.Z3805A, ReceiverModel.Z3801A, ReceiverModel.Z3816A, ReceiverModel.HP58503],
)
def test_no_other_model_claims_the_59551a_hardware(model: ReceiverModel) -> None:
    """The Z3805A row's SER2 cell is measured: ``:SYST:COMM:SER2:BAUD?`` answers
    ``-113,"Undefined header"`` on the live unit, which has one serial connector (#62)."""
    profile = model_profile.for_model(model)

    assert not profile.has_second_serial_port
    assert not profile.has_programmable_pulse_output
    assert not profile.has_timestamp_memory
    assert not profile.has_pps_edge_control


def test_no_identity_gets_the_conservative_profile() -> None:
    assert model_profile.for_identity(None) == model_profile.CONSERVATIVE


def test_an_identity_selects_its_model_s_profile() -> None:
    identity = DeviceIdentity.parse("SYMMETRICOM,59551A,1,1")

    assert model_profile.for_identity(identity).has_timestamp_memory


@pytest.mark.parametrize(
    "mnemonic",
    [
        ":PULS:PER",
        ":PULSe:PERiod",
        ":SYST:COMM:SER2:BAUD?",
        ":PTIM:PPS:EDGE",
        ":PTIMe:PPS:EDGE",
        ":SENS:DATA:VALue?",
        ":SENSe:TSTamp1:DATA?",
        ":FORM:DATA",
    ],
)
def test_a_z3805a_is_not_offered_the_59551a_commands(mnemonic: str) -> None:
    """Today this holds vacuously — none of them is in the catalog — which is the point: adding one
    later cannot quietly offer it on hardware without the feature."""
    assert model_profile.for_model(ReceiverModel.Z3805A).supports(mnemonic) is False
    assert model_profile.for_model(ReceiverModel.HP59551).supports(mnemonic) is True


@pytest.mark.parametrize("mnemonic", [":SYST:STAT?", "*IDN?", ":GPS:REF:ADEL", ":SYNC:TINT?"])
def test_a_command_no_row_restricts_is_supported_everywhere(mnemonic: str) -> None:
    assert model_profile.for_model(ReceiverModel.Z3805A).supports(mnemonic) is True
    assert model_profile.CONSERVATIVE.supports(mnemonic) is True


@pytest.mark.parametrize("mnemonic", [None, "", "   "])
def test_a_command_that_is_not_a_command_is_not_supported(mnemonic: str | None) -> None:
    assert model_profile.CONSERVATIVE.supports(mnemonic) is False


def test_the_first_serial_port_is_currently_caught_by_the_second_s_rule() -> None:
    """**This documents a hazard, not a desired behaviour**, and it is inherited rather than
    introduced: ``_starts_with_node`` lets *either* side be the abbreviation, exactly as
    ``ModelProfile.StartsWithNode`` does in WinZ3805A, so the node ``SER`` prefix-matches the
    restricted ``SER2`` and the **first** serial port's commands are refused too.

    It holds vacuously today — §16.1's inventory (#154) keeps every one of these out of the
    catalog, so nothing asks — which is why it has never been observed. It stops being vacuous the
    moment Phase 3 adds a ``:SYST:COMM:SER:*`` command, and this test is here so that lands as a
    failure with a name rather than as a missing feature nobody can account for.

    Deliberately not fixed here. §8.6's exclusion list is one of the two things
    ``docs/provenance.md`` says must not drift between the two repositories, and correcting the
    rule on one side only is how it drifts. Surfaced, not silently resolved.
    """
    assert model_profile.for_model(ReceiverModel.Z3805A).supports(":SYST:COMM:SER:BAUD?") is False
    assert model_profile.for_model(ReceiverModel.HP59551).supports(":SYST:COMM:SER:BAUD?") is True


# ---- The self-test subsystems -------------------------------------------------------------


def test_all_twelve_probed_keywords_are_present() -> None:
    """Twelve were sent to the live receiver on 28 Aug 2026 and all twelve were accepted — against
    a Quick Reference listing twelve and a Command Reference listing eleven."""
    assert len(self_test_subsystem.KNOWN) == 12
    assert {s.keyword for s in self_test_subsystem.KNOWN} == {
        "ALL",
        "DISP",
        "PROC",
        "RAM",
        "EEPR",
        "UART",
        "QSPI",
        "FPGA",
        "INT",
        "IREF",
        "GPS",
        "POW",
    }


def test_iref_is_present_though_the_command_reference_omits_it() -> None:
    """The Command Reference (5-54) drops ``IREFerence``; the receiver accepted it."""
    assert self_test_subsystem.by_keyword("IREF") is not None


def test_the_sweep_is_the_receiver_s_own_and_comes_first() -> None:
    """One command at 12.4 s, rather than eleven sequential runs at close to a minute."""
    assert self_test_subsystem.ALL.keyword == "ALL"
    assert self_test_subsystem.KNOWN[0] == self_test_subsystem.ALL


@pytest.mark.parametrize("keyword", ["GPS", "gps", " GpS "])
def test_a_keyword_is_matched_however_the_receiver_cases_its_echo(keyword: str) -> None:
    subsystem = self_test_subsystem.by_keyword(keyword)

    assert subsystem is not None
    assert subsystem.display_name == "GPS"


@pytest.mark.parametrize("keyword", [None, "", "   ", "ZZNOSUCH", "GP"])
def test_an_unknown_keyword_is_none(keyword: str | None) -> None:
    """``:DIAG:TEST? ZZNOSUCH`` returned ``-224,"Illegal parameter value"`` — the control that made
    the twelve accepted keywords mean something."""
    assert self_test_subsystem.by_keyword(keyword) is None


# ---- The diagnostic log entry -------------------------------------------------------------


def test_an_entry_is_structured_only_with_both_halves_of_its_prefix() -> None:
    stamp = datetime(2006, 1, 1, 5, 10, 4, tzinfo=UTC)

    assert DiagnosticLogEntry(raw_text="x", message="x", number=1, timestamp=stamp).is_structured
    assert not DiagnosticLogEntry(raw_text="x", message="x", number=1).is_structured
    assert not DiagnosticLogEntry(raw_text="x", message="x", timestamp=stamp).is_structured
    assert not DiagnosticLogEntry(raw_text="x", message="x").is_structured
