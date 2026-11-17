"""Strategiekiezer met geheugen dat langzaam vervaagt.

Elke candle krijgt elke strategie een (virtuele) beloning: wat ze na kosten zou
hebben verdiend, ook als de bot haar op dat moment niet volgt. Oude resultaten
tellen steeds minder mee (discount), zodat de bot zich aanpast als de markt
verandert.

Omdat alle strategieën altijd beoordeeld worden, hoeft de bot niet "op de gok"
te experimenteren. Hij kiest voorzichtig: de strategie met de hoogste ondergrens
(gemiddelde min `z` keer de onzekerheid). Is geen enkele strategie aantoonbaar
beter dan niets doen, dan wint Cash.
"""
import math


class DiscountedThompson:
    def __init__(self, arms, gamma=0.998, prior_sd=20.0):
        self.arms = list(arms)
        self.gamma = gamma
        self.prior_var = prior_sd ** 2
        self.s = {a: 0.0 for a in self.arms}       # som beloningen (bps)
        self.q = {a: 0.0 for a in self.arms}       # som kwadraten
        self.n = {a: 0.0 for a in self.arms}       # effectief aantal waarnemingen
        self.total = {a: 0.0 for a in self.arms}   # totale virtuele log-return

    def update(self, rewards_bps):
        g = self.gamma
        for a in self.arms:
            r = rewards_bps.get(a, 0.0)
            self.s[a] = self.s[a] * g + r
            self.q[a] = self.q[a] * g + r * r
            self.n[a] = self.n[a] * g + 1
            self.total[a] += r / 1e4

    def posterior(self, a):
        n = self.n[a] + 1  # één pseudo-waarneming met gemiddelde 0
        mean = self.s[a] / n
        var = max((self.q[a] + self.prior_var) / n - mean * mean, 1e-6)
        return mean, math.sqrt(var / n)

    def lower_bound(self, a, z):
        mean, sd = self.posterior(a)
        return mean - z * sd

    def choose(self, z=1.0):
        return max(self.arms, key=lambda a: self.lower_bound(a, z))

    def probabilities(self, rng, draws=400):
        """Kans dat elke strategie op dit moment echt de beste is (voor het dashboard)."""
        wins = {a: 0 for a in self.arms}
        post = {a: self.posterior(a) for a in self.arms}
        for _ in range(draws):
            wins[max(self.arms, key=lambda a: rng.gauss(*post[a]))] += 1
        return {a: wins[a] / draws for a in self.arms}
