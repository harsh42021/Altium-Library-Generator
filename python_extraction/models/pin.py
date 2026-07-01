"""
Core data models for the Altium Library Generator.

These are the canonical structures produced by extraction/classification.
They get serialized to JSON as the handoff format to the C# GUI, which
renders them into DelphiScript for Altium to consume.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ElectricalType(str, Enum):
    """Altium's native pin electrical types — we map to these directly
    so the DelphiScript generator doesn't need its own translation layer."""
    INPUT = "Input"
    OUTPUT = "Output"
    IO = "IO"
    OPEN_COLLECTOR = "OpenCollector"
    PASSIVE = "Passive"
    HIZ = "HiZ"
    OPEN_EMITTER = "OpenEmitter"
    POWER = "Power"
    UNKNOWN = "Unknown"


class DriveStructure(str, Enum):
    """Internal pin structure, as described in datasheet electrical
    characteristics / pin description tables. Informational — feeds
    into schematic pin visual style and review-stage sanity checks."""
    PUSH_PULL = "push-pull"
    OPEN_DRAIN = "open-drain"
    OPEN_SOURCE = "open-source"
    ANALOG = "analog"
    TRISTATE = "tristate"
    SCHMITT = "schmitt-trigger"
    UNKNOWN = "unknown"


class DiffPairRole(str, Enum):
    POSITIVE = "P"
    NEGATIVE = "N"
    NONE = "none"


@dataclass
class AlternateFunction:
    """A single alt-function entry from a pinmux table, e.g. PA9 -> USART1_TX (AF7)."""
    function_name: str
    interface_group: Optional[str] = None   # e.g. "UART1" — filled in by classifier
    mux_code: Optional[str] = None          # e.g. "AF7", raw from datasheet
    notes: Optional[str] = None


@dataclass
class Pin:
    pin_number: str                # string because of "A1", "PAD", etc.
    primary_name: str              # datasheet's default/reset function name
    electrical_type: ElectricalType = ElectricalType.UNKNOWN
    drive_structure: DriveStructure = DriveStructure.UNKNOWN
    diff_pair_role: DiffPairRole = DiffPairRole.NONE
    diff_pair_partner: Optional[str] = None   # pin number of the paired signal
    alternate_functions: list[AlternateFunction] = field(default_factory=list)
    functional_group: Optional[str] = None    # assigned by classifier, e.g. "SPI1", "POWER"
    side_hint: Optional[str] = None           # "left" | "right" | "top" | "bottom"
    is_no_connect: bool = False
    source_confidence: float = 1.0            # <1.0 flags rows needing manual review
    raw_source_text: Optional[str] = None      # original table row, for debugging/review UI
    display_label: Optional[str] = None        # e.g. "GPIO10/RCVRD_CLK_OUT2/TCK" — main function
                                                # first, alt functions joined with "/", matching
                                                # the datasheet's own compound naming convention.
                                                # Computed during classification; used as the
                                                # actual pin label on the schematic symbol.

    def all_names(self) -> list[str]:
        return [self.primary_name] + [af.function_name for af in self.alternate_functions]

    def compute_display_label(self) -> str:
        return "/".join(self.all_names())


@dataclass
class PinGroup:
    """A functional cluster of pins that becomes one visual block on the
    schematic symbol (or one sub-part, for multi-part symbols)."""
    name: str                      # e.g. "POWER", "SPI1", "DDR_DATA"
    pins: list[Pin] = field(default_factory=list)
    side: str = "left"             # left/right/top/bottom per the L-to-R convention
    part_index: int = 1            # which sub-part (multi-part symbol) this belongs to


@dataclass
class ComponentRecord:
    part_number: str
    manufacturer: Optional[str] = None
    pin_count: int = 0
    pins: list[Pin] = field(default_factory=list)
    groups: list[PinGroup] = field(default_factory=list)
    package_type: Optional[str] = None
    is_multi_part: bool = False
    extraction_warnings: list[str] = field(default_factory=list)
