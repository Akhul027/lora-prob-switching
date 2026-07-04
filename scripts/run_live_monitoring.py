import csv
import json
import os
import time
import threading
from datetime import datetime
from enum import Enum
from collections import deque

import matplotlib
matplotlib.use("TkAgg")

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Patch

import paho.mqtt.client as mqtt


# ================================================================
# MQTT CONFIG
# ================================================================

MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883

TOPIC_TELEMETRY = "vms_hybrid_2026/telemetry"
TOPIC_DECISION = "vms_hybrid_2026/switching_decision"

MQTT_QOS = 1

# ================================================================
# MODEL CONFIG
# ================================================================

OMEGA_RSSI = 0.5
OMEGA_SNR = 0.3
OMEGA_DISTANCE = 0.2

RSSI_MIN = -120.0
RSSI_MAX = -70.0  # BUG #6 FIXED: Diturunkan agar sensitivitas lebih tinggi (tidak terlalu optimistis)

SNR_MIN = -20.0
SNR_MAX = 10.0

DISTANCE_MIN = 0.0
DISTANCE_MAX = 15.0

P_HIGH = 0.70
P_SAFE = 0.75
P_LOW = 0.30

# ================================================================
# CSV
# ================================================================

CSV_FILENAME = "data/raw/vms_telemetry.csv"
CSV_RAD_FILENAME = "data/raw/vms_radiation.csv"

# Buat file CSV telemetri — append mode, header hanya ditulis sekali
_tel_is_new = not os.path.exists(CSV_FILENAME)
_csv_tel_file = open(CSV_FILENAME, "a", newline="")
_csv_tel_writer = csv.writer(_csv_tel_file)
if _tel_is_new:
    _csv_tel_writer.writerow([
        "timestamp", "seq_num",
        "distance_m", "RSSI_dBm", "SNR_dB",
        "P_LoRa", "state_label",
        "packet_sent", "packet_received", "packet_status",
        "radiation_wm2"
    ])

# Buat file CSV radiasi — append mode, header hanya ditulis sekali
_rad_is_new = not os.path.exists(CSV_RAD_FILENAME)
_csv_rad_file = open(CSV_RAD_FILENAME, "a", newline="")
_csv_rad_writer = csv.writer(_csv_rad_file)
if _rad_is_new:
    _csv_rad_writer.writerow([
        "timestamp", "seq_num",
        "radiation_wm2", "state_label",
        "RSSI_dBm", "SNR_dB", "distance_m", "P_LoRa"
    ])

# ================================================================
# DATA BUFFER
# ================================================================

MAX_POINTS = 300

time_data = deque(maxlen=MAX_POINTS)
rssi_data = deque(maxlen=MAX_POINTS)
snr_data = deque(maxlen=MAX_POINTS)
pdr_data = deque(maxlen=MAX_POINTS)
plora_data = deque(maxlen=MAX_POINTS)
distance_data = deque(maxlen=MAX_POINTS)
state_data = deque(maxlen=MAX_POINTS)
packet_status_data = deque(maxlen=MAX_POINTS)
radiation_data = deque(maxlen=MAX_POINTS)

data_lock = threading.Lock()

# ================================================================
# COUNTER
# ================================================================

packet_ok = 0
packet_lost = 0
switch_count = 0

# ================================================================
# STATE ENUM
# ================================================================

class SystemState(Enum):
    LORA = 0
    SWITCHING = 1
    STARLINK = 2


# ================================================================
# HELPER
# ================================================================

def clamp01(x):
    return max(0.0, min(1.0, x))

def normalize(value, vmin, vmax):
    if vmax <= vmin:
        return 0.0
    return clamp01(
        (value - vmin) / (vmax - vmin)
    )

def compute_p_lora(rssi, snr, distance_km):
    rssi_norm = normalize(rssi, RSSI_MIN, RSSI_MAX)
    snr_norm = normalize(snr, SNR_MIN, SNR_MAX)
    distance_norm = 1.0 - normalize(
        distance_km, DISTANCE_MIN, DISTANCE_MAX
    )
    p = (
        OMEGA_RSSI * rssi_norm
        + OMEGA_SNR * snr_norm
        + OMEGA_DISTANCE * distance_norm
    )
    return round(p, 4)


# ================================================================
# SWITCHER
# ================================================================

class Switcher:

    def __init__(self):
        self.state = SystemState.LORA

    def update(self, p_lora):
        global switch_count

        old_state = self.state

        if self.state == SystemState.LORA:
            if p_lora < P_LOW:
                self.state = SystemState.STARLINK
            elif p_lora < P_SAFE:
                self.state = SystemState.SWITCHING

        elif self.state == SystemState.SWITCHING:
            if p_lora >= P_HIGH:
                self.state = SystemState.LORA
            elif p_lora < P_LOW:
                self.state = SystemState.STARLINK

        elif self.state == SystemState.STARLINK:
            if p_lora > P_HIGH:
                self.state = SystemState.SWITCHING

        if old_state != self.state:
            switch_count += 1

        return self.state


# ================================================================
# REALTIME DASHBOARD
# ================================================================

class Dashboard:

    def __init__(self):
        self.fig = plt.figure(figsize=(22, 14), constrained_layout=True)
        self.fig.suptitle(
            "Probabilistic Switching LoRa vs Starlink\n"
            "Implementasi Bab 3.8 & 3.9",
            fontsize=14,
            fontweight="bold"
        )

        gs = gridspec.GridSpec(
            5, 2,
            figure=self.fig,
            width_ratios=[3, 1],
            hspace=0.65,
            wspace=0.40,
            top=0.93,
            bottom=0.06,
            left=0.07,
            right=0.97
        )

        self.ax1 = self.fig.add_subplot(gs[0, 0])
        self.ax2 = self.fig.add_subplot(gs[1, 0])
        self.ax3 = self.fig.add_subplot(gs[2, 0])
        self.ax4 = self.fig.add_subplot(gs[3, 0])
        self.ax5 = self.fig.add_subplot(gs[4, 0])

        self.ax_rad_plot  = self.fig.add_subplot(gs[0:2, 1])
        self.ax_rad_table = self.fig.add_subplot(gs[2:5, 1])
        self.ax_rad_table.axis("off")

        self.anim = FuncAnimation(
            self.fig,
            self.update,
            interval=500,
            cache_frame_data=False
        )

    def update(self, frame):
        self.ax1.clear()
        self.ax2.clear()
        self.ax3.clear()
        self.ax4.clear()
        self.ax5.clear()
        self.ax_rad_plot.clear()
        self.ax_rad_table.clear()
        self.ax_rad_table.axis("off")

        # BUG #1 FIXED: Menambahkan data_lock dan memastikan return masuk dalam blok if
        with data_lock:
            n = min(
                len(time_data),
                len(rssi_data),
                len(snr_data),
                len(plora_data),
                len(distance_data),
                len(state_data),
                len(packet_status_data),
                len(radiation_data)
            )

            if n < 2:
                return
            
            # Membuat snapshot data yang aman untuk di-render
            time_list = list(time_data)
            rssi_list = list(rssi_data)
            snr_list = list(snr_data)
            plora_list = list(plora_data)
            distance_list = list(distance_data)
            state_list = list(state_data)
            packet_status_list = list(packet_status_data)
            radiation_list = list(radiation_data) # Snapshot untuk BUG #4 dan #5

        x = time_list

        # ── Panel 1: RSSI + SNR ──────────────
        self.ax1.plot(x, rssi_list, label="RSSI")
        ax1b = self.ax1.twinx()
        ax1b.plot(x, snr_list, linestyle="--", label="SNR")
        self.ax1.set_title("Kualitas Sinyal LoRa: RSSI dan SNR")
        self.ax1.set_ylabel("RSSI (dBm)")
        ax1b.set_ylabel("SNR (dB)")
        self.ax1.grid(True)

        # ── Panel 2: P_LoRa ──────────────────
        self.ax2.plot(x, plora_list, label="P_LoRa")
        self.ax2.axhline(y=P_HIGH, linestyle="--", label=f"P_high = {P_HIGH}")
        self.ax2.axhline(y=P_LOW, linestyle="--", label=f"P_low = {P_LOW}")
        self.ax2.axhline(y=P_SAFE, linestyle=":", label=f"P_safe = {P_SAFE}")
        self.ax2.fill_between(x, P_LOW, P_SAFE, alpha=0.2, label="Zona hysteresis")
        self.ax2.set_ylim(0, 1)
        self.ax2.set_title("Probabilitas Keberhasilan Komunikasi LoRa (Bab 3.8.3)")
        self.ax2.set_ylabel("P_LoRa")
        self.ax2.grid(True)
        self.ax2.legend(loc="lower left", fontsize=8, ncol=4)

        # ── Panel 3: State ────────────────────
        for i, s in enumerate(state_list):
            if s == 0:
                color = "limegreen"
            elif s == 1:
                color = "orange"
            else:
                color = "red"
            self.ax3.bar(i, 1, color=color)

        self.ax3.set_title("State Komunikasi (Bab 3.9)")
        self.ax3.set_ylabel("State")
        self.ax3.set_yticks([0, 1, 2])
        self.ax3.set_yticklabels(["LoRa", "Switching", "Starlink"])
        self.ax3.grid(True)
        self.ax3.legend(
            handles=[
                Patch(color="limegreen", label="LoRa Aktif"),
                Patch(color="orange",    label="Switching/Booting"),
                Patch(color="red",       label="Starlink Aktif"),
            ],
            loc="upper right",
            fontsize=8
        )

        # ── Panel 4: Packet status ────────────
        ok_x   = []
        lost_x = []
        for i, s in enumerate(packet_status_list):
            if s == 1:
                ok_x.append(i)
            else:
                lost_x.append(i)

        self.ax4.scatter(ok_x,   [1] * len(ok_x),   s=8, label="OK")
        self.ax4.scatter(lost_x, [0] * len(lost_x), s=8, label="LOST")
        self.ax4.set_title("Status Pengiriman Paket per Step (Bab 3.4 - PDR)")
        self.ax4.set_ylabel("Paket")
        self.ax4.set_yticks([0, 1])
        self.ax4.set_yticklabels(["LOST", "OK"])
        self.ax4.grid(True)
        self.ax4.legend(fontsize=8)

        # ── Panel 5: Jarak ───────────────────
        self.ax5.plot(x, distance_list)
        self.ax5.axhline(y=5000, linestyle=":", label="D_max = 5000 m")
        self.ax5.set_title("Jarak Kapal terhadap Gateway")
        self.ax5.set_ylabel("Jarak (m)")
        self.ax5.set_xlabel("Time Step")
        self.ax5.grid(True)
        self.ax5.legend(fontsize=8)

        # ── Panel 6: Grafik radiasi ───────────────
        rlist = radiation_list  # BUG #5 FIXED: Menggunakan snapshot
        self.ax_rad_plot.plot(x, rlist, color="#FF5722", linewidth=1.2)
        self.ax_rad_plot.axhline(1000, linestyle=":", color="orange", linewidth=1, label="1000 W/m²")
        self.ax_rad_plot.set_title("Solar Radiation\n(SEM228A)", fontsize=9)
        self.ax_rad_plot.set_ylabel("W/m²", fontsize=8)
        self.ax_rad_plot.set_xlabel("Time Step", fontsize=8)
        self.ax_rad_plot.set_ylim(0, 1900)
        self.ax_rad_plot.grid(True, alpha=0.3)
        self.ax_rad_plot.legend(fontsize=7)

        # ── Panel 7: Tabel radiasi ────────────────
        n_tab = min(12, len(radiation_list)) # BUG #5 FIXED: Menggunakan snapshot
        if n_tab >= 1:
            t_vals   = time_list[-n_tab:]
            r_vals   = radiation_list[-n_tab:]
            s_vals   = state_list[-n_tab:]
            p_vals   = plora_list[-n_tab:]

            STATE_NAME  = {0: "LoRa", 1: "Switch", 2: "Starlink"}
            STATE_COLOR = {
                "LoRa":     "#C8E6C9",
                "Switch":   "#FFE0B2",
                "Starlink": "#FFCDD2"
            }

            rows = []
            for i in range(n_tab):
                rows.append([
                    str(t_vals[i]),
                    f"{r_vals[i]:.0f}",
                    f"{p_vals[i]:.3f}",
                    STATE_NAME.get(s_vals[i], "-")
                ])

            tbl = self.ax_rad_table.table(
                cellText=rows,
                colLabels=["Step", "Rad\n(W/m²)", "P_LoRa", "State"],
                loc="upper center",
                cellLoc="center"
            )
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(7)
            tbl.scale(1, 1.15)

            for j in range(4):
                tbl[0, j].set_facecolor("#37474F")
                tbl[0, j].set_text_props(color="white", fontweight="bold")

            for i, row in enumerate(rows):
                color = STATE_COLOR.get(row[3], "white")
                for j in range(4):
                    tbl[i + 1, j].set_facecolor(color)

            self.ax_rad_table.set_title("Tabel Radiasi\n(12 Data Terakhir)", fontsize=8, pad=4)

        # ── Footer ────────────────────────────
        total = packet_ok + packet_lost
        pdr_total = (packet_ok / total * 100) if total > 0 else 0
        
        # BUG #4 FIXED: Menggunakan snapshot radiation_list sehingga aman selama n >= 2
        rad_now = radiation_list[-1]

        footer = (
            f"PDR Total: {pdr_total:.2f}%   |   "
            f"Packet Loss: {100 - pdr_total:.2f}%   |   "
            f"Switching: {switch_count}x   |   "
            f"Radiasi: {rad_now:.0f} W/m²"
        )
        self.fig.text(
            0.5, 0.01, footer,
            ha="center", fontsize=10,
            bbox=dict(facecolor="wheat")
        )


# ================================================================
# MQTT BRIDGE
# ================================================================

class VMSBridge:

    def __init__(self):
        self.dashboard = Dashboard()
        self.switcher = Switcher()
        self.packet_count = 0

        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, rc):
        print(f"[MQTT] Connected to broker")
        client.subscribe(TOPIC_TELEMETRY)
        print(f"[MQTT] Subscribe: {TOPIC_TELEMETRY}")

    def on_message(self, client, userdata, msg):
        global packet_ok
        global packet_lost

        try:
            telemetry = json.loads(msg.payload.decode())

            self.packet_count += 1
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            rssi        = float(telemetry["rssi"])
            snr         = float(telemetry["snr"])

            # BUG #3 FIXED: Clamp dilakukan SEBELUM menghitung P_LoRa
            rssi = max(-120.0, min(-20.0, rssi))
            snr  = max(-20.0, min(20.0, snr))

            distance_km = float(telemetry["distance_km"])
            pdr         = float(telemetry["pdr_percent"])

            radiation = float(telemetry.get("radiation_wm2", 0.0))

            p_lora = compute_p_lora(rssi, snr, distance_km)
            state  = self.switcher.update(p_lora)

            # BUG #2 FIXED: Memasukkan seluruh update data ke dalam data_lock
            with data_lock:
                time_data.append(self.packet_count)
                rssi_data.append(rssi)
                snr_data.append(snr)
                pdr_data.append(pdr)
                plora_data.append(p_lora)
                distance_data.append(distance_km * 1000)
                state_data.append(state.value)
                radiation_data.append(radiation)

                if pdr > 80:
                    packet_status_data.append(1)
                    packet_ok += 1
                else:
                    packet_status_data.append(0)
                    packet_lost += 1

            # Menulis CSV telemetri
            _csv_tel_writer.writerow([
                ts,
                self.packet_count,
                round(distance_km * 1000, 1),
                rssi, snr,
                p_lora, state.name,
                packet_ok + packet_lost,
                packet_ok,
                "OK" if pdr > 80 else "LOST",
                radiation
            ])
            _csv_tel_file.flush()

            # Menulis CSV radiasi
            _csv_rad_writer.writerow([
                ts,
                self.packet_count,
                radiation,
                state.name,
                rssi, snr,
                round(distance_km * 1000, 1),
                p_lora
            ])
            _csv_rad_file.flush()

            # Decision
            target = "STARLINK" if state == SystemState.STARLINK else "LORA"
            self.client.publish(TOPIC_DECISION, target)

            # Terminal output
            print(
                f"[#{self.packet_count:04d}] "
                f"RSSI={rssi:6.1f} "
                f"SNR={snr:5.1f} "
                f"D={distance_km:5.2f}km "
                f"PDR={pdr:5.1f}% "
                f"Rad={radiation:6.1f}W/m² "
                f"P={p_lora:.3f} "
                f"STATE={state.name}"
            )

        except Exception as e:
            print(f"[ERROR] {e}")

    def run(self):
        print("=" * 70)
        print(" VMS PROBABILISTIC SWITCHING DASHBOARD")
        print(f" CSV Telemetri : {CSV_FILENAME}")
        print(f" CSV Radiasi   : {CSV_RAD_FILENAME}")
        print("=" * 70)

        self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.client.loop_start()

        try:
            plt.show()
        finally:
            _csv_tel_file.close()
            _csv_rad_file.close()
            print(f"\n[INFO] Data tersimpan:")
            print(f"       {CSV_FILENAME}")
            print(f"       {CSV_RAD_FILENAME}")

        self.client.loop_stop()


if __name__ == "__main__":
    bridge = VMSBridge()
    bridge.run()