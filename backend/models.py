from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DataEntry:
    data_type: str
    host: str 
    location: str 
    lineage_hash: str 
    amstrax_version: str 
    raw: dict[str, Any]


@dataclass
class RunSummary:
    number: int
    mode: str 
    start: datetime 
    end: datetime 
    processing_status: str 
    has_raw_records: bool
    has_events: bool
    has_led_calibration: bool
    science_run_id: str
    run_class: str
    source_type: str
    # corrections versions of the stored event_info entries ("online" = no version recorded)
    corrections: list[str] = field(default_factory=list)


@dataclass
class RunDetails:
    number: int
    mode: str 
    start: datetime 
    end: datetime 
    tags: list[dict[str, Any]]
    comments: list[dict[str, Any]]
    processing_status: dict[str, Any] 
    data_entries: list[DataEntry]
    raw_doc: dict[str, Any]
