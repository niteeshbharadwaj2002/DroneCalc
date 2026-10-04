"""Mission screen: requirements, environment, ranking and the advanced model settings."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dronecalc.core import SCORERS, atmosphere
from dronecalc.ui.state import AppState
from dronecalc.ui.widgets import NumberField, OptionalNumberField

SCORER_TEXT = {
    "flight_time": "Longest flight time",
    "lightest": "Lightest",
    "cheapest": "Cheapest",
    "efficiency": "Highest hover efficiency",
}


class MissionScreen(QWidget):
    runRequested = Signal()
    reverseRequested = Signal()

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        root = QVBoxLayout(self)

        # --- mode -----------------------------------------------------------------------
        mode_box = QGroupBox("Mode")
        ml = QHBoxLayout(mode_box)
        self.fwd = QRadioButton("Forward sizing: find builds for a mission")
        self.rev = QRadioButton("Reverse sizing: evaluate a chosen set of components")
        self.fwd.setChecked(True)
        ml.addWidget(self.fwd)
        ml.addWidget(self.rev)
        root.addWidget(mode_box)

        # --- mission --------------------------------------------------------------------
        box = QGroupBox("Mission")
        form = QFormLayout(box)
        self.time = NumberField(1, 120, 20, 1, 0, " min")
        self.payload = NumberField(0, 10, 0.5, 0.05, 2, " kg")
        self.altitude = NumberField(0, 6000, 0, 50, 0, " m")
        self.temp = NumberField(-40, 40, 0, 1, 0, " K")
        self.rotors = QComboBox()
        for n, name in ((4, "Quad (4 rotors)"), (6, "Hex (6 rotors)"), (8, "Octo (8 rotors)")):
            self.rotors.addItem(name, n)
        self.payload_power = NumberField(0, 200, 0, 1, 0, " W", slider=False)
        self.max_mass = OptionalNumberField(
            "Limit takeoff mass", 0.1, 100, 5, decimals=1, suffix=" kg"
        )
        self.max_budget = OptionalNumberField(
            "Limit component cost", 10, 20000, 800, decimals=0, suffix=" USD"
        )
        self.frame_override = OptionalNumberField(
            "Override frame mass", 10, 20000, 500, decimals=0, suffix=" g"
        )
        self.target_label = QLabel("Target flight time")
        form.addRow(self.target_label, self.time)
        form.addRow("Payload mass", self.payload)
        form.addRow("Payload power draw", self.payload_power)
        form.addRow("Altitude above sea level", self.altitude)
        form.addRow("Temperature offset from ISA", self.temp)
        form.addRow("Configuration", self.rotors)
        form.addRow(self.max_mass)
        form.addRow(self.max_budget)
        form.addRow(self.frame_override)
        self.atm_label = QLabel()
        self.atm_label.setStyleSheet("color: palette(mid);")
        form.addRow("Air at this site", self.atm_label)
        root.addWidget(box)

        # --- ranking --------------------------------------------------------------------
        rbox = QGroupBox("Ranking (forward mode)")
        rform = QFormLayout(rbox)
        self.scorer = QComboBox()
        for key in SCORERS:
            self.scorer.addItem(SCORER_TEXT.get(key, key), key)
        self.top_n = QSpinBox()
        self.top_n.setRange(1, 100)
        self.top_n.setValue(10)
        rform.addRow("Rank by", self.scorer)
        rform.addRow("Show top", self.top_n)
        root.addWidget(rbox)

        # --- advanced -------------------------------------------------------------------
        self.advanced = QGroupBox("Advanced: tick to edit model assumptions and constraints")
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        adv = QFormLayout(self.advanced)
        a = state.assumptions
        c = state.constraints
        self.dod = NumberField(0.1, 1.0, a.depth_of_discharge, 0.01, 2, slider=False)
        self.esc_eff = NumberField(0.5, 1.0, a.esc_efficiency, 0.01, 2, slider=False)
        self.wiring = NumberField(0, 0.3, a.wiring_fraction, 0.01, 2, slider=False)
        self.derate = NumberField(0, 0.6, a.flight_time_derate, 0.01, 2, slider=False)
        self.av_power = NumberField(0, 100, a.avionics_power_w, 0.5, 1, " W", slider=False)
        self.av_mass = NumberField(0, 2000, a.avionics_mass_g, 5, 0, " g", slider=False)
        self.clearance = NumberField(0, 1.0, a.prop_clearance, 0.01, 2, slider=False)
        self.max_thr = NumberField(0.3, 1.0, c.max_hover_throttle, 0.01, 2, slider=False)
        self.min_tw = NumberField(1.0, 6.0, c.min_thrust_to_weight, 0.1, 2, slider=False)
        self.chk_power = QCheckBox("Check motor power limit")
        self.chk_c = QCheckBox("Check battery C-rate limits")
        self.chk_power.setChecked(c.check_motor_power)
        self.chk_c.setChecked(c.check_battery_c_rate)
        adv.addRow("Depth of discharge", self.dod)
        adv.addRow("ESC efficiency", self.esc_eff)
        adv.addRow("Wiring fraction of dry mass", self.wiring)
        adv.addRow("Extra flight-time derate", self.derate)
        adv.addRow("Avionics power", self.av_power)
        adv.addRow("Avionics mass", self.av_mass)
        adv.addRow("Prop tip clearance (x diameter)", self.clearance)
        adv.addRow("Max hover throttle", self.max_thr)
        adv.addRow("Min thrust-to-weight", self.min_tw)
        adv.addRow(self.chk_power)
        adv.addRow(self.chk_c)
        self.reset_btn = QPushButton("Reset to defaults")
        adv.addRow(self.reset_btn)
        root.addWidget(self.advanced)

        # --- run ------------------------------------------------------------------------
        self.run_btn = QPushButton("Run forward sizing")
        self.run_btn.setDefault(True)
        self.run_btn.setMinimumHeight(36)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(mid);")
        root.addWidget(self.run_btn)
        root.addWidget(self.hint)
        root.addStretch(1)

        self._wire()
        self.refresh()

    # ---- wiring ----------------------------------------------------------------------------

    def _wire(self) -> None:
        s = self.state
        self.time.valueChanged.connect(lambda v: s.update_mission(target_flight_time_min=v))
        self.payload.valueChanged.connect(lambda v: s.update_mission(payload_kg=v))
        self.payload_power.valueChanged.connect(lambda v: s.update_mission(payload_power_w=v))
        self.altitude.valueChanged.connect(lambda v: s.update_mission(altitude_m=v))
        self.temp.valueChanged.connect(lambda v: s.update_mission(temp_offset_c=v))
        self.rotors.currentIndexChanged.connect(
            lambda _i: s.update_mission(n_rotors=self.rotors.currentData())
        )
        self.max_mass.valueChanged.connect(lambda v: s.update_mission(max_mass_kg=v))
        self.max_budget.valueChanged.connect(lambda v: s.update_mission(max_budget_usd=v))
        self.frame_override.valueChanged.connect(
            lambda v: s.update_mission(frame_mass_override_g=v)
        )
        self.scorer.currentIndexChanged.connect(
            lambda _i: s.set_ranking(scorer=self.scorer.currentData())
        )
        self.top_n.valueChanged.connect(lambda v: s.set_ranking(top_n=v))
        self.fwd.toggled.connect(lambda on: s.set_mode("forward") if on else None)
        self.rev.toggled.connect(lambda on: s.set_mode("reverse") if on else None)

        self.dod.valueChanged.connect(lambda v: s.update_assumptions(depth_of_discharge=v))
        self.esc_eff.valueChanged.connect(lambda v: s.update_assumptions(esc_efficiency=v))
        self.wiring.valueChanged.connect(lambda v: s.update_assumptions(wiring_fraction=v))
        self.derate.valueChanged.connect(lambda v: s.update_assumptions(flight_time_derate=v))
        self.av_power.valueChanged.connect(lambda v: s.update_assumptions(avionics_power_w=v))
        self.av_mass.valueChanged.connect(lambda v: s.update_assumptions(avionics_mass_g=v))
        self.clearance.valueChanged.connect(lambda v: s.update_assumptions(prop_clearance=v))
        self.max_thr.valueChanged.connect(lambda v: s.update_constraints(max_hover_throttle=v))
        self.min_tw.valueChanged.connect(lambda v: s.update_constraints(min_thrust_to_weight=v))
        self.chk_power.toggled.connect(lambda v: s.update_constraints(check_motor_power=v))
        self.chk_c.toggled.connect(lambda v: s.update_constraints(check_battery_c_rate=v))
        self.reset_btn.clicked.connect(s.reset_model_settings)
        self.run_btn.clicked.connect(self._run)

        s.missionChanged.connect(self.refresh)
        s.settingsChanged.connect(self.refresh)
        s.busyChanged.connect(self._busy)

    def _run(self) -> None:
        if self.state.mode == "forward":
            self.runRequested.emit()
        else:
            self.reverseRequested.emit()

    def _busy(self, busy: bool) -> None:
        self.run_btn.setEnabled(not busy)

    # ---- state -> widgets ------------------------------------------------------------------

    def refresh(self) -> None:
        s = self.state
        m, a, c = s.mission, s.assumptions, s.constraints
        self.time.setValue(m.target_flight_time_min)
        self.payload.setValue(m.payload_kg)
        self.payload_power.setValue(m.payload_power_w)
        self.altitude.setValue(m.altitude_m)
        self.temp.setValue(m.temp_offset_c)
        self.rotors.blockSignals(True)
        self.rotors.setCurrentIndex(self.rotors.findData(m.n_rotors))
        self.rotors.blockSignals(False)
        self.max_mass.setValue(m.max_mass_kg)
        self.max_budget.setValue(m.max_budget_usd)
        self.frame_override.setValue(m.frame_mass_override_g)
        for w, v in (
            (self.dod, a.depth_of_discharge),
            (self.esc_eff, a.esc_efficiency),
            (self.wiring, a.wiring_fraction),
            (self.derate, a.flight_time_derate),
            (self.av_power, a.avionics_power_w),
            (self.av_mass, a.avionics_mass_g),
            (self.clearance, a.prop_clearance),
            (self.max_thr, c.max_hover_throttle),
            (self.min_tw, c.min_thrust_to_weight),
        ):
            w.setValue(v)
        for chk, v in ((self.chk_power, c.check_motor_power), (self.chk_c, c.check_battery_c_rate)):
            chk.blockSignals(True)
            chk.setChecked(v)
            chk.blockSignals(False)
        self.scorer.blockSignals(True)
        self.scorer.setCurrentIndex(self.scorer.findData(s.scorer))
        self.scorer.blockSignals(False)
        self.top_n.blockSignals(True)
        self.top_n.setValue(s.top_n)
        self.top_n.blockSignals(False)
        for btn, on in ((self.fwd, s.mode == "forward"), (self.rev, s.mode == "reverse")):
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)

        forward = s.mode == "forward"
        for w in (self.time, self.max_mass, self.max_budget, self.scorer, self.top_n):
            w.setEnabled(forward)
        self.target_label.setEnabled(forward)
        self.run_btn.setText("Run forward sizing" if forward else "Evaluate selected components")
        self.hint.setText(
            "Finds motor, propeller, battery and ESC combinations that meet the mission."
            if forward
            else "Choose motor, propeller, battery and ESC on the Components screen; this "
            "predicts flight time and the maximum payload."
        )

        atm = atmosphere(m.altitude_m, m.temp_offset_c)
        self.atm_label.setText(
            f"density {atm.density:.3f} kg/m3 | {atm.temperature_c:.1f} C | "
            f"density altitude {round(atm.density_altitude_m)} m"
        )
