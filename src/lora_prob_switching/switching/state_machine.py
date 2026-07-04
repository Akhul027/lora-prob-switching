import csv
import json
import os
import time
from datetime import datetime
from enum import Enum
from collections import deque

import matplotlib
matplotlib.use("TkAgg")

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

import paho.mqtt.client as mqtt


# ================================================================
# MQTT CONFIG
# ================================================================

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883

TOPIC_TELEMETRY = "vms_hybrid_2026/telemetry"
TOPIC_DECISION = "vms_hybrid_2026/switching_decision"

MQTT_QOS = 1

PUBLISH_DECISION = True

# ================================================================
# MODEL CONFIG
# ================================================================

OMEGA_RSSI = 0.5
OMEGA_SNR = 0.3
OMEGA_DISTANCE = 0.2

RSSI_MIN = -120.0
RSSI_MAX = -30.0

SNR_MIN = -20.0
SNR_MAX = 10.0

DISTANCE_MIN = 0.0
DISTANCE_MAX = 15.0

P_LOW = 0.35
P_SAFE = 0.55

# ================================================================
# CSV
# ================================================================

CSV_FILENAME = "vms_telemetry_dataset.csv"

CSV_HEADER = [
    "RSSI_dBm",
    "SNR_dB",
    "Distance_km",
    "Radiation_Wm2",
    "Expected_Packets",
    "Received_Packets",
    "Packet_Loss",
    "PDR_Percent",
    "P_LoRa",
    "State",
    "Target_Link",
    "Timestamp",
]

# ================================================================
# DATA BUFFER (REALTIME)
# ================================================================

MAX_POINTS = 100

rssi_data = deque(maxlen=MAX_POINTS)
snr_data = deque(maxlen=MAX_POINTS)
pdr_data = deque(maxlen=MAX_POINTS)
plora_data = deque(maxlen=MAX_POINTS)

# ================================================================
# STATE ENUM
# ================================================================


class SystemState(Enum):

    LORA_ACTIVE = "LORA"

    STARLINK_ACTIVE = "STARLINK"


# ================================================================
# HELPER
# ================================================================


def clamp01(x):

    return max(0.0, min(1.0, x))


# ================================================================


def normalize(value, vmin, vmax):

    if vmax <= vmin:
        return 0.0

    return clamp01(
        (value - vmin) / (vmax - vmin)
    )


# ================================================================


def compute_p_lora(rssi, snr, distance_km):

    rssi_norm = normalize(
        rssi,
        RSSI_MIN,
        RSSI_MAX
    )

    snr_norm = normalize(
        snr,
        SNR_MIN,
        SNR_MAX
    )

    distance_norm = 1.0 - normalize(
        distance_km,
        DISTANCE_MIN,
        DISTANCE_MAX
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

        self.state = SystemState.LORA_ACTIVE

    # ============================================================

    def update(self, rssi, snr, distance_km):

        p_lora = compute_p_lora(
            rssi,
            snr,
            distance_km
        )

        # ========================================================

        if p_lora < P_LOW:

            self.state = (
                SystemState.STARLINK_ACTIVE
            )

        elif p_lora >= P_SAFE:

            self.state = (
                SystemState.LORA_ACTIVE
            )

        # ========================================================

        target = (
            "STARLINK"
            if self.state
            == SystemState.STARLINK_ACTIVE
            else "LORA"
        )

        return {

            "state":
                self.state.value,

            "target_link":
                target,

            "p_lora":
                p_lora,

            "distance_km":
                round(distance_km, 3),

            "timestamp":
                time.time(),
        }


# ================================================================
# CSV LOGGER
# ================================================================


class CsvLogger:

    def __init__(self, filename):

        self.filename = filename

        self._init_file()

    # ============================================================

    def _init_file(self):

        file_exists = os.path.isfile(
            self.filename
        )

        self.file = open(
            self.filename,
            mode="a",
            newline="",
            encoding="utf-8"
        )

        self.writer = csv.writer(self.file)

        if not file_exists:

            self.writer.writerow(CSV_HEADER)

            self.file.flush()

            print(
                f"[CSV] File dibuat: "
                f"{self.filename}"
            )

    # ============================================================

    def log(self, telemetry, decision, pdr):

        row = [

            telemetry.get("rssi", 0.0),

            telemetry.get("snr", 0.0),

            decision["distance_km"],

            telemetry.get(
                "radiation_wm2",
                0.0
            ),

            pdr["expected"],

            pdr["received"],

            pdr["packet_loss"],

            pdr["pdr_percent"],

            decision["p_lora"],

            decision["state"],

            decision["target_link"],

            datetime.fromtimestamp(
                decision["timestamp"]
            ).isoformat(),
        ]

        self.writer.writerow(row)

        self.file.flush()

    # ============================================================

    def close(self):

        self.file.close()


# ================================================================
# REALTIME GRAPH
# ================================================================


class RealtimeGraph:

    def __init__(self):

        self.fig, self.axs = plt.subplots(
            4,
            1,
            figsize=(12, 10)
        )

        self.ani = FuncAnimation(
            self.fig,
            self.update,
            interval=500,
            cache_frame_data=False
        )

    # ============================================================

    def update(self, frame):

        for ax in self.axs:
            ax.clear()

        x = range(len(rssi_data))

        # ========================================================

        self.axs[0].plot(
            x,
            list(rssi_data)
        )

        self.axs[0].set_title(
            "RSSI"
        )

        self.axs[0].grid(True)

        # ========================================================

        self.axs[1].plot(
            x,
            list(snr_data)
        )

        self.axs[1].set_title(
            "SNR"
        )

        self.axs[1].grid(True)

        # ========================================================

        self.axs[2].plot(
            x,
            list(pdr_data)
        )

        self.axs[2].set_title(
            "PDR"
        )

        self.axs[2].grid(True)

        # ========================================================

        self.axs[3].plot(
            x,
            list(plora_data)
        )

        self.axs[3].axhline(
            y=P_LOW,
            linestyle="--"
        )

        self.axs[3].axhline(
            y=P_SAFE,
            linestyle="--"
        )

        self.axs[3].set_title(
            "P_LoRa"
        )

        self.axs[3].grid(True)

        plt.tight_layout()


# ================================================================
# VMS BRIDGE
# ================================================================


class VmsBridge:

    def __init__(self):

        self.switcher = Switcher()

        self.csv = CsvLogger(
            CSV_FILENAME
        )

        self.graph = RealtimeGraph()

        self.packet_count = 0

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=(
                f"vms_python_"
                f"{int(time.time())}"
            ),
        )

        self.client.on_connect = (
            self._on_connect
        )

        self.client.on_message = (
            self._on_message
        )

    # ============================================================

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties
    ):

        if reason_code == 0:

            print(
                f"[MQTT] Connected "
                f"to "
                f"{MQTT_BROKER}:"
                f"{MQTT_PORT}"
            )

            client.subscribe(
                TOPIC_TELEMETRY,
                qos=MQTT_QOS
            )

            print(
                f"[MQTT] Subscribed: "
                f"{TOPIC_TELEMETRY}\n"
            )

    # ============================================================

    def _on_message(
        self,
        client,
        userdata,
        msg
    ):

        try:

            telemetry = json.loads(
                msg.payload.decode()
            )

            self.packet_count += 1

            # ====================================================

            rssi = float(
                telemetry["rssi"]
            )

            snr = float(
                telemetry["snr"]
            )

            distance_km = float(
                telemetry["distance_km"]
            )

            radiation = float(
                telemetry.get(
                    "radiation_wm2",
                    0
                )
            )

            # ====================================================

            pdr_stats = {

                "expected":
                    telemetry.get(
                        "expected_packet",
                        0
                    ),

                "received":
                    telemetry.get(
                        "received_packet",
                        0
                    ),

                "packet_loss":
                    telemetry.get(
                        "packet_loss",
                        0
                    ),

                "pdr_percent":
                    telemetry.get(
                        "pdr_percent",
                        0.0
                    ),
            }

            # ====================================================

            decision = self.switcher.update(
                rssi,
                snr,
                distance_km
            )

            # ====================================================
            # UPDATE REALTIME GRAPH BUFFER
            # ====================================================

            rssi_data.append(rssi)

            snr_data.append(snr)

            pdr_data.append(
                pdr_stats["pdr_percent"]
            )

            plora_data.append(
                decision["p_lora"]
            )

            # ====================================================

            self.csv.log(
                telemetry,
                decision,
                pdr_stats
            )

            # ====================================================

            if PUBLISH_DECISION:

                self.client.publish(
                    TOPIC_DECISION,
                    decision["target_link"],
                    qos=MQTT_QOS
                )

            # ====================================================

            print(
                f"[#{self.packet_count:04d}] "
                f"RSSI={rssi:6.1f} "
                f"SNR={snr:5.1f} "
                f"d={distance_km:5.2f}km "
                f"Rad={radiation:5.0f} "
                f"PDR={pdr_stats['pdr_percent']:5.1f}% "
                f"P={decision['p_lora']:.3f} "
                f"[{decision['state']:10s}] "
                f"-> "
                f"{decision['target_link']}"
            )

        except Exception as e:

            print(f"[ERROR] {e}")

    # ============================================================

    def run(self):

        print("=" * 70)

        print(
            " VMS PROBABILISTIC "
            "SWITCHING + REALTIME GRAPH"
        )

        print("=" * 70)

        self.client.connect(
            MQTT_BROKER,
            MQTT_PORT,
            keepalive=60
        )

        self.client.loop_start()

        plt.show()

        self.client.loop_stop()

        self.csv.close()


# ================================================================
# MAIN
# ================================================================

if __name__ == "__main__":

    bridge = VmsBridge()

    bridge.run()