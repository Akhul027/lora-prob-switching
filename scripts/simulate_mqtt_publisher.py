import json
import math
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

MQTT_HOST = "broker.emqx.io"
MQTT_PORT = 1883
MQTT_TOPIC = "vms_hybrid_2026/telemetry"

DEVICE_ID = "SIM-KAPAL-01"

P_LOW = 0.30
P_HIGH = 0.70
D_MAX = 6000.0

BASE_LAT = -7.2575
BASE_LON = 112.7521


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def make_client():
    try:
        return mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{DEVICE_ID}-publisher",
        )
    except AttributeError:
        return mqtt.Client(client_id=f"{DEVICE_ID}-publisher")


def build_payload(packet_id, active_link):
    phase = (math.sin(packet_id / 18.0) + 1) / 2
    distance_m = 300 + phase * 6500

    rssi = -55 - (distance_m / 80.0) + random.uniform(-4, 4)
    snr = 12 - (distance_m / 700.0) + random.uniform(-1.5, 1.5)

    rssi_norm = clamp((rssi - (-120)) / ((-45) - (-120)))
    snr_norm = clamp((snr - (-15)) / (15 - (-15)))
    d_norm = clamp(1 - (distance_m / D_MAX))

    p_lora = clamp((0.50 * rssi_norm) + (0.20 * snr_norm) + (0.30 * d_norm))

    if active_link == "LORA" and p_lora < P_LOW:
        active_link = "STARLINK"
    elif active_link == "STARLINK" and p_lora > P_HIGH:
        active_link = "LORA"

    lat = BASE_LAT + (distance_m / 111000.0) * 0.15
    lon = BASE_LON + (distance_m / 111000.0) * 0.85

    payload = {
        "device_id": DEVICE_ID,
        "packet_id": packet_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),

        "lat": round(lat, 7),
        "lon": round(lon, 7),
        "latitude": round(lat, 7),
        "longitude": round(lon, 7),

        "distance_m": round(distance_m, 2),
        "rssi": round(rssi, 2),
        "snr": round(snr, 2),
        "p_lora": round(p_lora, 3),

        "active_link": active_link,
        "communication_mode": active_link,
        "relay_status": "ON" if active_link == "STARLINK" else "OFF",
        "relay_starlink": active_link == "STARLINK",
    }

    return payload, active_link


def main():
    client = make_client()
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    print(f"Publish dummy telemetry ke mqtt://{MQTT_HOST}:{MQTT_PORT}/{MQTT_TOPIC}")
    print("CTRL+C untuk stop.\n")

    packet_id = 0
    active_link = "LORA"

    try:
        while True:
            payload, active_link = build_payload(packet_id, active_link)
            msg = json.dumps(payload)

            client.publish(MQTT_TOPIC, msg, qos=0)

            print(
                f"[{packet_id:04d}] "
                f"mode={payload['active_link']} "
                f"p_lora={payload['p_lora']} "
                f"rssi={payload['rssi']} "
                f"snr={payload['snr']} "
                f"jarak={payload['distance_m']}m"
            )

            packet_id += 1
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
