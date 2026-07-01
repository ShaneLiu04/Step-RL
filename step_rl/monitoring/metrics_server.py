"""Prometheus metrics server for production monitoring."""

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server

    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False


class MetricsServer:
    """Exposes Step-RL metrics via Prometheus on a configurable HTTP port.

    Args:
        port: Port on which the Prometheus HTTP server listens.
    """

    def __init__(self, port: int = 9090):
        self._has_prometheus = HAS_PROMETHEUS
        if self._has_prometheus:
            self._setup_metrics()
            start_http_server(port)

    def _setup_metrics(self):
        self.episode_counter = Counter(
            "step_rl_episodes_total", "Total episodes completed"
        )
        self.step_latency = Histogram(
            "step_rl_step_latency_seconds", "Per-step latency in seconds"
        )
        self.success_rate = Gauge(
            "step_rl_success_rate", "Current rolling success rate"
        )
        self.grounding_acc = Gauge(
            "step_rl_grounding_accuracy", "Current grounding accuracy"
        )
        self.reward_total = Counter("step_rl_reward_total", "Cumulative reward sum")
        self.kl_divergence = Gauge(
            "step_rl_kl_divergence", "Current KL divergence estimate"
        )

    def inc_episodes(self, amount: int = 1):
        """Increment total episode counter."""
        if self._has_prometheus:
            self.episode_counter.inc(amount)

    def observe_step_latency(self, seconds: float):
        """Observe a single step latency."""
        if self._has_prometheus:
            self.step_latency.observe(seconds)

    def set_success_rate(self, rate: float):
        """Set current success rate gauge (0.0–1.0)."""
        if self._has_prometheus:
            self.success_rate.set(rate)

    def set_grounding_accuracy(self, acc: float):
        """Set current grounding accuracy gauge (0.0–1.0)."""
        if self._has_prometheus:
            self.grounding_acc.set(acc)

    def add_reward(self, value: float):
        """Add reward to cumulative reward counter."""
        if self._has_prometheus:
            self.reward_total.inc(value)

    def set_kl_divergence(self, kl: float):
        """Set KL divergence gauge."""
        if self._has_prometheus:
            self.kl_divergence.set(kl)
