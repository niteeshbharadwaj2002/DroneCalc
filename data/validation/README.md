# Validation reference data

`reference_points.csv` holds thrust-table points used by `dronecalc validate`.

| Column | Meaning |
|---|---|
| `motor_id`, `prop_id` | Ids that exist in the component database (`data/seed` or `data/custom`) |
| `voltage_v` | Supply voltage during the test |
| `thrust_g` | Measured static thrust of one motor, grams |
| `current_a`, `power_w` | Measured battery-side current / power (at least one required) |
| `source` | Where the number came from (datasheet URL, test report) |
| `altitude_m`, `temp_offset_c` | Optional test conditions (default ISA sea level) |

**The file ships empty on purpose.** No reference data was invented. Phase 1's exit criterion
(>= 10 motor/prop/voltage combinations within +/-15% on power, plus a documented eCalc
comparison) cannot be claimed until real rows are added. Check each source's licence before
copying community bench data.
