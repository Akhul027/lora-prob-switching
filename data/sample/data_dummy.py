"""
Generator data dummy realistik untuk simulasi LoRa maritim.
Skenario: kapal bergerak nearshore -> offshore -> nearshore.
"""
import numpy as np


def generate_realistic_lora_data(n_steps: int, d_max: float):
    """
    Hasilkan jarak (m), RSSI (dBm), dan SNR (dB) yang merepresentasikan
    pergerakan kapal.

    Skenario:
      - 0 - n/3       : nearshore (jarak naik dari 100 m)
      - n/3 - 2n/3    : offshore  (jarak mendekati / melebihi D_MAX)
      - 2n/3 - n      : kembali nearshore
    """
    rng = np.random.default_rng(42)
    t = np.arange(n_steps)

    # Profil jarak: segitiga (naik lalu turun) dengan noise kecil
    half = n_steps // 2
    ramp_up   = np.linspace(100, d_max * 1.05, half)
    ramp_down = np.linspace(d_max * 1.05, 100, n_steps - half)
    d = np.concatenate([ramp_up, ramp_down])
    d = d + rng.normal(0, 50, n_steps)
    d = np.clip(d, 50, d_max * 1.1)

    # RSSI menurun dengan jarak (model log-distance disederhanakan) + noise
    # Pada d ~ 100 m  : RSSI ~ -55 dBm
    # Pada d ~ D_MAX  : RSSI ~ -118 dBm  (offshore -> sinyal sangat lemah)
    rssi_base = -55 - 16.0 * np.log10(d / 100.0)
    rssi = rssi_base + rng.normal(0, 3.0, n_steps)
    rssi = np.clip(rssi, -120, -40)

    # SNR menurun dengan jarak + noise
    snr_base = 8.0 - 9.0 * np.log10(d / 100.0)
    snr = snr_base + rng.normal(0, 1.5, n_steps)
    snr = np.clip(snr, -20, 10)

    return d, rssi, snr