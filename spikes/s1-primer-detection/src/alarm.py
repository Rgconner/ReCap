"""GPIO alarm output — drives relay/transistor outputs wired to the X-10's
built-in alarm jacks (shorting one triggers its pulsing-lights + beep).

Each detection action (WARN/STOP) can trigger one or more named outputs,
either as a timed pulse or a held latch. Takes the GPIO module as a
constructor argument (real RPi.GPIO on the Pi, a mock in tests) so this is
fully testable off-hardware.
"""
import threading


class AlarmController:
    def __init__(self, gpio_module, outputs, policies):
        """outputs: list of setup_config.AlarmOutput.
        policies: list of setup_config.AlarmPolicy."""
        self._gpio = gpio_module
        self._outputs = {o.id: o for o in outputs}
        self._policies = {p.action: p for p in policies}
        self._latched = set()
        self._timers = {}

        for output in self._outputs.values():
            self._gpio.setup(output.gpio_pin, self._gpio.OUT, initial=self._idle_state(output))

    def _idle_state(self, output):
        return self._gpio.LOW if output.active_high else self._gpio.HIGH

    def _engaged_state(self, output):
        return self._gpio.HIGH if output.active_high else self._gpio.LOW

    def _drive(self, output_id, engaged):
        output = self._outputs[output_id]
        state = self._engaged_state(output) if engaged else self._idle_state(output)
        self._gpio.output(output.gpio_pin, state)

    def trigger(self, action):
        """Fires the outputs configured for this action, per its policy.
        No-op if no policy is configured for the action."""
        policy = self._policies.get(action)
        if not policy:
            return

        for output_id in policy.outputs:
            if output_id not in self._outputs:
                continue
            self._drive(output_id, engaged=True)
            if policy.mode == "pulse":
                self._schedule_release(output_id, policy.pulse_ms)
            else:  # latch
                # A pulse for this output may already be scheduled (e.g. an
                # earlier WARN) — without cancelling it, that timer would
                # later fire and release the pin while _latched still
                # thinks it's held, so hardware and software disagree.
                self._cancel_pending_release(output_id)
                self._latched.add(output_id)

    def _cancel_pending_release(self, output_id):
        existing = self._timers.pop(output_id, None)
        if existing:
            existing.cancel()

    def _schedule_release(self, output_id, pulse_ms):
        self._cancel_pending_release(output_id)
        timer = threading.Timer(pulse_ms / 1000, self._drive, args=(output_id, False))
        timer.daemon = True
        timer.start()
        self._timers[output_id] = timer

    def any_latched(self) -> bool:
        """True if any output is currently latched — i.e. needs an
        acknowledgment before it releases."""
        return bool(self._latched)

    def clear(self, output_id=None):
        """Releases a latched output (or all latched outputs). The hook for
        a future acknowledge mechanism (button/API/timeout) — nothing calls
        this yet besides this method existing."""
        targets = [output_id] if output_id else list(self._latched)
        for oid in targets:
            if oid in self._outputs:
                self._drive(oid, engaged=False)
            self._latched.discard(oid)

    def test_pulse(self, output_id, pulse_ms=300):
        """Manual bring-up helper — fires one output directly, bypassing
        policy lookup. See main.py --test-alarm."""
        if output_id not in self._outputs:
            raise KeyError(f"No alarm output named {output_id!r}")
        self._drive(output_id, engaged=True)
        self._schedule_release(output_id, pulse_ms)

    def cleanup(self):
        for timer in self._timers.values():
            timer.cancel()
        for output_id in list(self._outputs):
            self._drive(output_id, engaged=False)
