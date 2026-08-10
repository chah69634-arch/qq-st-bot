# Manual sensor evidence

`tests/manual/smoke_sensor_*.py` are manual smoke programs, not pytest tests
and not Android/device acceptance. Run the command from the repository root
against a redacted device or simulator source, then use
`.github/workflows/manual-sensor-evidence.yml` to record:

- the exact backend SHA;
- the redacted device/simulator identity;
- the command, synthetic/redacted input, and observed output;
- UTC execution time and an evidence URL or artifact reference.

The workflow only records supplied evidence. It does not manufacture a PASS
from a mocked event, and an absent run remains `not-run` in release readiness.
