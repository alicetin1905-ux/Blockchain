"""Online logistische regressie: leert bij elke nieuwe candle een beetje bij.

Het model schat de kans dat de koers binnen `horizon` candles meer stijgt dan
de kosten van een koop en verkoop samen.
"""
import math
from collections import deque


def _sigmoid(s):
    if s >= 0:
        return 1 / (1 + math.exp(-s))
    e = math.exp(s)
    return e / (1 + e)


class OnlineLogReg:
    def __init__(self, n, lr=0.05, l2=1e-4, window=500):
        self.n = n
        self.lr = lr
        self.l2 = l2
        self.w = [0.0] * n
        self.b = 0.0
        self.gw = [1e-8] * n   # AdaGrad: stapgrootte per feature
        self.gb = 1e-8
        self.cnt = 0           # lopend gemiddelde/variantie voor normalisatie
        self.mean = [0.0] * n
        self.m2 = [0.0] * n
        self.updates = 0
        self.positives = 0
        self.hist = deque(maxlen=window)  # (voorspelling, uitkomst) voor de score

    def observe(self, x):
        """Werk de normalisatie bij met een nieuw feature-vector (Welford)."""
        self.cnt += 1
        for i, v in enumerate(x):
            d = v - self.mean[i]
            self.mean[i] += d / self.cnt
            self.m2[i] += d * (v - self.mean[i])

    def _z(self, x):
        if self.cnt < 2:
            return [0.0] * self.n
        out = []
        for i, v in enumerate(x):
            sd = math.sqrt(self.m2[i] / (self.cnt - 1))
            z = (v - self.mean[i]) / sd if sd > 1e-12 else 0.0
            out.append(max(-5.0, min(5.0, z)))
        return out

    def _score(self, z):
        return self.b + sum(w * v for w, v in zip(self.w, z))

    def predict(self, x):
        return _sigmoid(self._score(self._z(x)))

    def update(self, x, y):
        z = self._z(x)
        p = _sigmoid(self._score(z))
        self.hist.append((p, y))  # gemeten vóór het leren van dit voorbeeld: eerlijke score
        g = p - y
        for i in range(self.n):
            grad = g * z[i] + self.l2 * self.w[i]
            self.gw[i] += grad * grad
            self.w[i] -= self.lr * grad / math.sqrt(self.gw[i])
        self.gb += g * g
        self.b -= self.lr * g / math.sqrt(self.gb)
        self.updates += 1
        self.positives += y

    @property
    def base_rate(self):
        return (self.positives + 1) / (self.updates + 2)

    def metrics(self):
        """Is het model beter dan gokken? Vergelijkt met 'altijd hetzelfde antwoord'."""
        if not self.hist:
            return {"samples": 0}
        n = len(self.hist)
        ys = [y for _, y in self.hist]
        rate = min(max(sum(ys) / n, 1e-6), 1 - 1e-6)
        acc = sum((p > 0.5) == bool(y) for p, y in self.hist) / n
        ll = -sum(math.log(max(p if y else 1 - p, 1e-9)) for p, y in self.hist) / n
        base_ll = -sum(math.log(rate if y else 1 - rate) for y in ys) / n
        return {
            "samples": n,
            "accuracy": acc,
            "majority_accuracy": max(rate, 1 - rate),
            "logloss": ll,
            "base_logloss": base_ll,
            "skill": 1 - ll / base_ll if base_ll > 0 else 0.0,  # >0 = beter dan gokken
            "up_rate": rate,
        }

    def top_weights(self, names, k=5):
        pairs = sorted(zip(names, self.w), key=lambda p: -abs(p[1]))
        return [{"feature": n, "weight": w} for n, w in pairs[:k]]
