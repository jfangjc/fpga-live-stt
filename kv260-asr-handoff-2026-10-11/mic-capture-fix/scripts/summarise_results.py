#!/usr/bin/env python3
"""Print a one-line pass/fail summary per cocotb results_<DUT>.xml (JUnit format)."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

total_fail = 0
for xml in sorted(Path(sys.argv[1] if len(sys.argv) > 1 else "sim").glob("results_*.xml")):
    cases = ET.parse(xml).getroot().iter("testcase")
    n = fail = 0
    for c in cases:
        n += 1
        if c.find("failure") is not None or c.find("error") is not None:
            fail += 1
    total_fail += fail
    print(f"{xml.stem[8:]:8s} {n - fail}/{n} passed")
sys.exit(1 if total_fail else 0)
