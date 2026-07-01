"""
Classifies pins into functional groups (POWER, SPI1, I2C1, UART, DDR, etc.)
and assigns each group a symbol side (left/right/top/bottom), following
the convention: inputs/control-in on the left, outputs/high-speed-out on
the right, power typically top/bottom.

Also handles multi-part symbol splitting for components with >20 pins,
grouping related interfaces onto the same sub-part where possible so a
designer isn't hunting across parts for one SPI bus.
"""
from __future__ import annotations
import re
from collections import defaultdict

from models.pin import Pin, PinGroup, ElectricalType, ComponentRecord, DiffPairRole

MULTI_PART_PIN_THRESHOLD = 20

# Ordered: more specific patterns first, so e.g. "SPI1_MOSI" doesn't get
# caught by a generic GPIO rule. Each entry: (group_name_template, regex, side)
INTERFACE_PATTERNS: list[tuple[str, str, str]] = [
    ("POWER",     r"^(V(DD|CC|SS|BAT|IN|OUT|REF|PP)|GND|AGND|DGND|VSSA|VDDA)\d*[A-Z]*$", "bottom"),
    ("RESET",     r"^(N?RST|RESET|NRST)\d*$", "left"),
    ("CLOCK",     r"^(X?TAL|OSC|CLK)(IN|OUT)?\d*$", "left"),
    ("JTAG_SWD",  r"^(TCK|TMS|TDI|TDO|TRST|SWDIO|SWCLK|SWO)$", "left"),
    ("SPI",       r"^SPI(\d*)_?(SCK|MOSI|MISO|CS|NSS|SS)$", "right"),
    ("I2C",       r"^I2C(\d*)_?(SCL|SDA)$", "right"),
    ("UART",      r"^U(S)?ART(\d*)_?(TX|RX|CTS|RTS)$", "right"),
    ("USB",       r"^USB(\d*)_?(DP|DM|D\+|D-|VBUS|ID)$", "right"),
    ("ETHERNET",  r"^(E(TH|NET))(\d*)_?(TX|RX|MDI|MDC|MDIO|CRS|COL|REF_CLK)", "right"),
    ("PCIE",      r"^PCIE?(\d*)_?(TX|RX|CLK|PERST|WAKE|REFCLK)", "right"),
    ("SERDES",    r"^(SERDES|LANE)(\d*)_?(TX|RX)[PN]?$", "right"),
    ("DDR",       r"^DDR\d?_?(A|BA|CK|CKE|CS|RAS|CAS|WE|DQ|DQS|DM|ODT|RESET)", "right"),
    ("ADC",       r"^(ADC|AIN|VIN_ANALOG)\d*$", "left"),
    ("PWM_TIMER", r"^(PWM|TIM(ER)?)\d*_?(CH)?\d*$", "right"),
]

GPIO_FALLBACK_PATTERN = r"^P[A-Z]\d+$|^GPIO\d*$|^IO\d*$"


def detect_diff_pair_role(candidate_names: list[str]) -> str:
    """Checks all candidate names (primary + alt functions) for
    differential-pair markers. Returns 'P', 'N', or 'none'.
    Must be checked across all names because the diff-pair designation
    often lives in an alt-function name (e.g. GPIO pin 'PA12' whose
    alt-function is 'USB_DP') rather than the primary pin name.

    Two naming styles are handled:
    - Trailing suffix: 'SGMII_TXP' / 'SGMII_TXN', 'USB_DP'/'USB_DM', '+'/'-'
    - Mid-string segment followed by a channel letter: 'TX_RXP_A' /
      'TX_RXN_A' (common when a device has multiple lettered channels/
      lanes, so P/N can't be the last segment)."""
    # Segment-based check handles names like TX_RXP_A where the P/N
    # marker is a middle segment (RXP/RXN), not the trailing one.
    # NOTE: deliberately does NOT treat a bare 'P' or 'N' segment as a
    # diff-pair marker on its own — trailing '_N' is extremely commonly
    # used for active-low signals (RESET_N, INT_N), not diff-pair
    # negative. Only DP/DM (unambiguous) or a P/N segment preceded by a
    # recognized differential-context prefix (TX/RX/etc.) counts.
    DIFF_PREFIXES = ("TX", "RX", "D", "AB", "CD", "LANE")
    for name in candidate_names:
        clean = re.sub(r"[\s]", "", name.strip().upper())
        segments = re.split(r"[_-]", clean)
        for seg in segments:
            if seg in ("DP",):
                return DiffPairRole.POSITIVE
            if seg in ("DM",):
                return DiffPairRole.NEGATIVE
            if len(seg) >= 2 and seg[-1] == "P" and seg[:-1] in DIFF_PREFIXES:
                return DiffPairRole.POSITIVE
            if len(seg) >= 2 and seg[-1] == "N" and seg[:-1] in DIFF_PREFIXES:
                return DiffPairRole.NEGATIVE
        if clean.endswith("+"):
            return DiffPairRole.POSITIVE
        if clean.endswith("-"):
            return DiffPairRole.NEGATIVE
    return DiffPairRole.NONE


def _strip_diff_suffix(name: str) -> str:
    """Removes trailing P/N or +/- so 'PCIE_TX0_P' and 'PCIE_TX0_N' group together."""
    return re.sub(r"([_-]?[PN]|[+-])$", "", name.upper())


def classify_pin(pin: Pin) -> tuple[str, str]:
    """Returns (group_name, side) for a single pin, checking primary name
    and alternate functions. Alt-function interfaces get appended as
    additional candidate groups for the review UI to disambiguate later
    (a pin can legitimately serve SPI1 in one config, GPIO in another)."""
    candidates = pin.all_names()
    pin.display_label = pin.compute_display_label()

    # Diff-pair role must be (re)checked here, not just at initial pin-table
    # parse time, since the diff-pair marker (e.g. USB_DP) often only shows
    # up once alt-functions from a pinmux table/description column are attached.
    detected_role = detect_diff_pair_role(candidates)
    if detected_role != DiffPairRole.NONE:
        pin.diff_pair_role = detected_role

    # GPIO pins whose PRIMARY (main) function is GPIOx get their own
    # group regardless of which datasheet table they were cross-
    # referenced against. Grouping follows the same "main function"
    # rule as the pin label: a pin datasheet-grouped under a catch-all
    # "Miscellaneous" table because it happens to default to GPIO
    # should still be grouped with other GPIOs, not lumped in with
    # unrelated analog/control pins (ISET, RES_REF, TEST_MODE, etc.)
    # that share that table for unrelated reasons. This also keeps the
    # multi-part splitter from producing one oversized mixed bucket.
    if re.match(GPIO_FALLBACK_PATTERN, pin.primary_name.strip().upper()):
        return "GPIO", "left"

    # If the structured datasheet parser already assigned a functional
    # group from the vendor's own table organization (e.g. "TABLE 3-3:
    # SGMII INTERFACE PINS"), trust it over regex guessing — it's
    # ground truth from the datasheet, not an inference.
    if pin.functional_group and pin.side_hint:
        return pin.functional_group, pin.side_hint

    for name in candidates:
        name_clean = name.strip().upper().replace(" ", "")
        for group_template, pattern, side in INTERFACE_PATTERNS:
            m = re.match(pattern, name_clean)
            if m:
                # Include bus index if the regex captured one, e.g. SPI1, I2C2
                idx = next((g for g in m.groups() if g and g.isdigit()), "")
                group_name = f"{group_template}{idx}" if idx else group_template
                return group_name, side

    # No specific interface matched — check power by name even without pattern hit
    if pin.electrical_type == ElectricalType.POWER:
        return "POWER", "bottom"

    if pin.is_no_connect:
        return "NO_CONNECT", "bottom"

    if re.match(GPIO_FALLBACK_PATTERN, pin.primary_name.strip().upper()):
        return "GPIO", "left"

    return "MISC", "left"


def build_groups(pins: list[Pin]) -> list[PinGroup]:
    grouped: dict[str, list[Pin]] = defaultdict(list)
    sides: dict[str, str] = {}

    for pin in pins:
        group_name, side = classify_pin(pin)
        pin.functional_group = group_name
        pin.side_hint = side
        grouped[group_name].append(pin)
        sides[group_name] = side

    return [
        PinGroup(name=name, pins=pins_list, side=sides[name])
        for name, pins_list in grouped.items()
    ]


def assign_multi_part(groups: list[PinGroup], pin_count: int) -> bool:
    """If pin_count exceeds threshold, splits groups across sub-parts.
    Strategy: each interface group stays whole within one part (never
    split a bus across parts); parts are filled greedily by pin count,
    with POWER duplicated onto every part per Altium convention (each
    sub-part typically carries its own power pins so it can be placed
    independently on the sheet)."""
    if pin_count <= MULTI_PART_PIN_THRESHOLD:
        for g in groups:
            g.part_index = 1
        return False

    # Simple greedy bin-packing by pin count, ~20 pins per part target
    target_per_part = MULTI_PART_PIN_THRESHOLD
    power_groups = [g for g in groups if g.name == "POWER"]
    other_groups = sorted(
        [g for g in groups if g.name != "POWER"],
        key=lambda g: -len(g.pins)
    )

    part_loads: list[int] = [0]
    part_index = 1
    for g in other_groups:
        if part_loads[part_index - 1] + len(g.pins) > target_per_part and part_loads[part_index - 1] > 0:
            part_index += 1
            part_loads.append(0)
        g.part_index = part_index
        part_loads[part_index - 1] += len(g.pins)

    total_parts = part_index
    for pg in power_groups:
        pg.part_index = 1  # primary power group lives on part 1; duplication
                            # onto other parts is handled by the DelphiScript
                            # generator (needs actual pin objects, not just
                            # the group reference)

    return total_parts > 1


def classify_component(part_number: str, pins: list[Pin], package_type: str | None = None) -> ComponentRecord:
    groups = build_groups(pins)
    is_multi = assign_multi_part(groups, len(pins))

    return ComponentRecord(
        part_number=part_number,
        pin_count=len(pins),
        pins=pins,
        groups=groups,
        package_type=package_type,
        is_multi_part=is_multi,
    )
