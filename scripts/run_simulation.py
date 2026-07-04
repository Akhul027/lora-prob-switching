from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec

from data.sample.data_dummy import generate_realistic_lora_data


RSSI_MIN, RSSI_MAX = -120.0, -40.0     # dBm
SNR_MIN,  SNR_MAX  = -20.0,  10.0      # dB
D_MAX              = 5000.0            # meter (jangkauan maksimal LoRa)


W1 = 0.4   # bobot RSSI  (dominan)
W2 = 0.2   # bobot SNR
W3 = 0.4   # bobot Jarak (dominan)

P_HIGH = 0.70   
P_LOW  = 0.30   
P_SAFE = 0.75   
                

LORA_ACTIVE     = 0
SWITCHING       = 1
STARLINK_ACTIVE = 2
STATE_LABEL     = {0: "LORA", 1: "SWITCHING", 2: "STARLINK"}

SWITCH_DELAY = 5  # step

P_STARLINK_SUCCESS = 0.98


def normalize_params(rssi: float, snr: float, d: float):
    """
    Implementasi rumus normalisasi sesuai Bab 3.8.2:
      RSSI_norm = (RSSI - RSSI_min) / (RSSI_max - RSSI_min)
      SNR_norm  = (SNR  - SNR_min)  / (SNR_max  - SNR_min)
      D_norm    = 1 - (D / D_max)
    """
    rssi_norm = (rssi - RSSI_MIN) / (RSSI_MAX - RSSI_MIN)
    snr_norm  = (snr  - SNR_MIN)  / (SNR_MAX  - SNR_MIN)
    d_norm    = 1.0 - (d / D_MAX)
    return rssi_norm, snr_norm, d_norm


def compute_p_lora(rssi: float, snr: float, d: float):
    """
    P_LoRa = w1*RSSI_norm + w2*SNR_norm + w3*D_norm
    dengan w1 + w2 + w3 = 1
    """
    rssi_n, snr_n, d_n = normalize_params(rssi, snr, d)
    p_lora = W1 * rssi_n + W2 * snr_n + W3 * d_n
    return p_lora, rssi_n, snr_n, d_n


def decide_switching(p_lora: float, state: int, switch_counter: int):

    if state == LORA_ACTIVE:
        if p_lora <= P_LOW:
            return SWITCHING, SWITCH_DELAY
        return LORA_ACTIVE, 0

    elif state == SWITCHING:
        if switch_counter > 0:
            return SWITCHING, switch_counter - 1
        return STARLINK_ACTIVE, 0

    elif state == STARLINK_ACTIVE:
        if p_lora >= P_SAFE:
            return LORA_ACTIVE, 0
        return STARLINK_ACTIVE, 0

    return state, switch_counter


def transmit_packet(state: int, p_lora: float, rng):

    if state == LORA_ACTIVE:
        received = 1 if rng.random() < p_lora else 0
    elif state == STARLINK_ACTIVE:
        received = 1 if rng.random() < P_STARLINK_SUCCESS else 0
    else:  # SWITCHING - tidak ada jalur aktif
        received = 0
    return 1, received


def calculate_metrics(df: pd.DataFrame) -> dict:
    """
    Hitung metrik sesuai Bab 3.4:
      - PDR (%) = paket diterima / paket dikirim x 100
      - Frekuensi switching (transisi LoRa <-> Starlink)
      - Waktu di tiap state
    """
    total_sent = int(df["packet_sent"].sum())
    total_recv = int(df["packet_received"].sum())
    pdr_total  = (total_recv / total_sent * 100) if total_sent > 0 else 0.0
    packet_loss = 100.0 - pdr_total

    df_lora = df[df["state"] == LORA_ACTIVE]
    df_sat  = df[df["state"] == STARLINK_ACTIVE]
    pdr_lora = (df_lora["packet_received"].sum() / df_lora["packet_sent"].sum() * 100) \
        if df_lora["packet_sent"].sum() > 0 else 0.0
    pdr_sat  = (df_sat["packet_received"].sum() / df_sat["packet_sent"].sum() * 100) \
        if df_sat["packet_sent"].sum() > 0 else 0.0

    df_active = df[df["state"].isin([LORA_ACTIVE, STARLINK_ACTIVE])].copy()
    n_switch  = int((df_active["state"].diff().fillna(0) != 0).sum())
    n_switch = max(0, n_switch - 1) if len(df_active) > 0 else 0

    return {
        "Total paket dikirim":      total_sent,
        "Total paket diterima":     total_recv,
        "PDR total (%)":            round(pdr_total, 2),
        "Packet Loss (%)":          round(packet_loss, 2),
        "PDR LoRa (%)":             round(pdr_lora, 2),
        "PDR Starlink (%)":         round(pdr_sat, 2),
        "LoRa aktif (step)":        int((df["state"] == LORA_ACTIVE).sum()),
        "Switching (step)":         int((df["state"] == SWITCHING).sum()),
        "Starlink aktif (step)":    int((df["state"] == STARLINK_ACTIVE).sum()),
        "Frekuensi switching":      n_switch,
        "Mean P_LoRa":              round(df["P_LoRa"].mean(), 4),
        "Min P_LoRa":               round(df["P_LoRa"].min(),  4),
        "Max P_LoRa":               round(df["P_LoRa"].max(),  4),
    }


def simulate_scenario(n_steps: int = 300, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d, rssi, snr = generate_realistic_lora_data(n_steps, D_MAX)

    state = LORA_ACTIVE
    switch_counter = 0
    seq_num = 0
    records = []

    for i in range(n_steps):
        p_lora, rssi_n, snr_n, d_n = compute_p_lora(rssi[i], snr[i], d[i])
        p_lora = max(0.0, min(1.0, p_lora))  # batasi ke [0, 1]

        state, switch_counter = decide_switching(p_lora, state, switch_counter)

        seq_num += 1
        sent, received = transmit_packet(state, p_lora, rng)

        records.append({
            "time":              i,
            "seq_num":           seq_num,
            "distance_m":        round(float(d[i]),    2),
            "RSSI_dBm":          round(float(rssi[i]), 2),
            "SNR_dB":            round(float(snr[i]),  2),
            "RSSI_norm":         round(rssi_n, 4),
            "SNR_norm":          round(snr_n,  4),
            "D_norm":            round(d_n,    4),
            "P_LoRa":            round(p_lora, 4),
            "state":             state,
            "state_label":       STATE_LABEL[state],
            "packet_sent":       sent,
            "packet_received":   received,
            "packet_status":     "OK" if received == 1 else "LOST",
        })

    return pd.DataFrame(records)


def plot_results(df: pd.DataFrame, metrics: dict, save_path: str = "results/figures/grafik_hasil.png"):
    fig = plt.figure(figsize=(16, 13))
    fig.patch.set_facecolor("white")
    gs = gridspec.GridSpec(5, 1, figure=fig, hspace=0.5)

    t = df["time"]
    COLOR_LORA = "#2ecc71"
    COLOR_SW   = "#f39c12"
    COLOR_SAT  = "#e74c3c"

    fig.suptitle(
        "Simulasi Probabilistic Switching LoRa vs Satelit\n"
        "Implementasi Bab 3.8 & 3.9",
        fontsize=13, fontweight="bold", y=0.99
    )

    ax1 = fig.add_subplot(gs[0])
    ax1.plot(t, df["RSSI_dBm"], color="#2874a6", linewidth=1.2, label="RSSI (dBm)")
    ax1.set_ylabel("RSSI (dBm)", color="#2874a6", fontsize=9)
    ax1.tick_params(axis="y", labelcolor="#2874a6", labelsize=8)
    ax1_r = ax1.twinx()
    ax1_r.plot(t, df["SNR_dB"], color="#d35400", linewidth=1.0, linestyle="--", label="SNR (dB)")
    ax1_r.set_ylabel("SNR (dB)", color="#d35400", fontsize=9)
    ax1_r.tick_params(axis="y", labelcolor="#d35400", labelsize=8)
    ax1.set_title("Kualitas Sinyal LoRa: RSSI dan SNR", fontsize=10, pad=4)
    ax1.grid(axis="y", alpha=0.3, linestyle=":")

    ax2 = fig.add_subplot(gs[1])
    ax2.plot(t, df["P_LoRa"], color="#2980b9", linewidth=1.4, label="P_LoRa")
    ax2.axhline(P_HIGH, color="green",  linestyle="--", linewidth=0.9, label=f"P_high = {P_HIGH}")
    ax2.axhline(P_LOW,  color="red",    linestyle="--", linewidth=0.9, label=f"P_low  = {P_LOW}")
    ax2.axhline(P_SAFE, color="purple", linestyle=":",  linewidth=0.9, label=f"P_safe = {P_SAFE}")
    ax2.fill_between(t, P_LOW, P_HIGH, alpha=0.07, color="gray", label="Zona hysteresis")
    ax2.set_ylabel("P_LoRa", fontsize=9)
    ax2.set_ylim(-0.05, 1.10)
    ax2.set_title("Probabilitas Keberhasilan Komunikasi LoRa (Bab 3.8.3)", fontsize=10, pad=4)
    ax2.legend(loc="lower left", fontsize=7, ncol=5)
    ax2.grid(axis="y", alpha=0.3, linestyle=":")

    ax3 = fig.add_subplot(gs[2])
    cmap = {LORA_ACTIVE: COLOR_LORA, SWITCHING: COLOR_SW, STARLINK_ACTIVE: COLOR_SAT}
    for i in range(len(df) - 1):
        ax3.fill_between(
            [t.iloc[i], t.iloc[i+1]], 0, 1,
            color=cmap[df["state"].iloc[i]], alpha=0.55
        )
    ax3.plot(t, df["state"], color="black", linewidth=0.9, drawstyle="steps-post")
    ax3.set_yticks([0, 1, 2])
    ax3.set_yticklabels(["LoRa", "Switching", "Starlink"], fontsize=8)
    ax3.set_ylabel("State", fontsize=9)
    ax3.set_title("State Komunikasi (Bab 3.9)", fontsize=10, pad=4)
    patches = [
        mpatches.Patch(color=COLOR_LORA, label="LoRa Aktif"),
        mpatches.Patch(color=COLOR_SW,   label="Switching/Booting"),
        mpatches.Patch(color=COLOR_SAT,  label="Starlink Aktif"),
    ]
    ax3.legend(handles=patches, loc="upper right", fontsize=8)

    ax4 = fig.add_subplot(gs[3])
    ok_mask   = df["packet_received"] == 1
    lost_mask = df["packet_received"] == 0
    ax4.scatter(t[ok_mask],   [1]*ok_mask.sum(),   color="green", s=8, label="OK")
    ax4.scatter(t[lost_mask], [0]*lost_mask.sum(), color="red",   s=8, label="LOST")
    ax4.set_yticks([0, 1])
    ax4.set_yticklabels(["LOST", "OK"], fontsize=8)
    ax4.set_ylabel("Paket", fontsize=9)
    ax4.set_ylim(-0.3, 1.3)
    ax4.set_title("Status Pengiriman Paket per Step (Bab 3.4 - PDR)", fontsize=10, pad=4)
    ax4.legend(loc="center right", fontsize=8)
    ax4.grid(axis="x", alpha=0.3, linestyle=":")

    ax5 = fig.add_subplot(gs[4])
    ax5.plot(t, df["distance_m"], color="#6c3483", linewidth=1.2)
    ax5.axhline(D_MAX, color="red", linestyle=":", linewidth=0.9, label=f"D_max = {int(D_MAX)} m")
    ax5.set_ylabel("Jarak (m)", fontsize=9)
    ax5.set_xlabel("Time Step", fontsize=9)
    ax5.set_title("Jarak Kapal terhadap Gateway", fontsize=10, pad=4)
    ax5.legend(loc="upper right", fontsize=8)
    ax5.grid(axis="y", alpha=0.3, linestyle=":")

    mt = (f"PDR Total: {metrics['PDR total (%)']:.2f}%   |   "
          f"Packet Loss: {metrics['Packet Loss (%)']:.2f}%   |   "
          f"PDR LoRa: {metrics['PDR LoRa (%)']:.2f}%   |   "
          f"PDR Starlink: {metrics['PDR Starlink (%)']:.2f}%   |   "
          f"Switching: {metrics['Frekuensi switching']}x")
    fig.text(0.5, 0.005, mt, ha="center", fontsize=9,
             bbox=dict(boxstyle="round,pad=0.4", fc="#fef9e7", ec="#888", lw=0.8))

    plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"Grafik disimpan: {save_path}")

    plt.show()


if __name__ == "__main__":
    print("=" * 65)
    print("  Probabilistic Switching LoRa vs Satelit")
    print("  Implementasi Bab 3.8 & 3.9 - Proposal Tugas Akhir")
    print("  Septyo Ajie Subito Audistyo")
    print("=" * 65)

    df = simulate_scenario(n_steps=300, seed=42)
    metrics = calculate_metrics(df)

    print("\n[METRIK PERFORMA - Bab 3.4]")
    for k, v in metrics.items():
        print(f"   {k:<28}: {v}")

    print("\n[SAMPLE DATA - 5 baris pertama]")
    cols_show = ["time", "seq_num", "distance_m", "RSSI_dBm", "SNR_dB",
                 "P_LoRa", "state_label", "packet_status"]
    print(df[cols_show].head().to_string(index=False))

    plot_results(df, metrics, "results/figures/grafik_hasil.png")
    df.to_csv("data/processed/hasil_simulasi.csv", index=False)
    print("\nFile disimpan: data/processed/hasil_simulasi.csv")
    print("File disimpan: results/figures/grafik_hasil.png")