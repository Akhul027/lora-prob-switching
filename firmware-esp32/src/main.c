#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "driver/uart.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "hardware_init.h"
#include "mbedtls/aes.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "mqtt_client.h"
#include "cJSON.h" 
// To Do
// Membaca pesan dan melakukan switching (belum menambahkan relay) 


// Ambil variabel dari location.c
extern const float BASE_LAT;
extern const float BASE_LON;
//kalau ga ada location.c
//const float BASE_LAT = -7.284916; 
//const float BASE_LON = 112.795808;

static const char *TAG_HW = "HARDWARE_INIT";

// ==============================================================================
// IMPLEMENTASI FUNGSI HARDWARE
// ==============================================================================
void button_init(void) {
    if(BUTTON_PIN != -1) {
        gpio_config_t btn_config = {
            .intr_type = GPIO_INTR_DISABLE,
            .mode = GPIO_MODE_INPUT,
            .pin_bit_mask = (1ULL << BUTTON_PIN),
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
        };
        gpio_config(&btn_config);
    }
}

void relay_init(void)
{
    gpio_reset_pin(STARLINK_RELAY_PIN);
    gpio_set_direction(STARLINK_RELAY_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(STARLINK_RELAY_PIN, 1);
}

void led_init(void) {
    if(GREEN_LED_PIN != -1) {
        gpio_reset_pin(GREEN_LED_PIN);
        gpio_set_direction(GREEN_LED_PIN, GPIO_MODE_OUTPUT);
    }
    if(RED_LED_PIN != -1) {
        gpio_reset_pin(RED_LED_PIN);
        gpio_set_direction(RED_LED_PIN, GPIO_MODE_OUTPUT);
    }
}

void m0_m1_lora_init(void) {
    if(LORA_M0_PIN != -1 && LORA_M1_PIN != -1) {
        gpio_config_t m0_m1_config = {
            .intr_type = GPIO_INTR_DISABLE,
            .mode = GPIO_MODE_OUTPUT,
            .pin_bit_mask = (1ULL << LORA_M0_PIN) | (1ULL << LORA_M1_PIN),
            .pull_down_en = 0,
            .pull_up_en = 0,
        };
        gpio_config(&m0_m1_config);
        gpio_set_level(LORA_M0_PIN, 0);
        gpio_set_level(LORA_M1_PIN, 0);
    }
}

void aux_lora_init(void) {
    if(LORA_AUX_PIN != -1) {
        gpio_config_t aux_config = {
            .mode = GPIO_MODE_INPUT,
            .pin_bit_mask = (1ULL << LORA_AUX_PIN),
            .pull_up_en = 1,
        };
        gpio_config(&aux_config);

        ESP_LOGI(TAG_HW, "Menunggu LoRa AUX stabil...");
        while(gpio_get_level(LORA_AUX_PIN) == 0) {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
    ESP_LOGI(TAG_HW, "Modul LoRa Siap pada Mode Mendengar (Default)!");
}

void uart_lora_init(void) {
    uart_config_t uart_config = {
        .baud_rate = LORA_BAUD_RATE,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_2, BUF_SIZE * 2, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_2, &uart_config));
    ESP_ERROR_CHECK(uart_set_pin(UART_NUM_2, LORA_TXD_PIN, LORA_RXD_PIN, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
}

void configure_lora_channel(void) {
    ESP_LOGI("LORA_CONFIG", "Memulai proses konfigurasi Register...");
    if(LORA_AUX_PIN != -1 && LORA_M0_PIN != -1 && LORA_M1_PIN != -1) {
        while(gpio_get_level(LORA_AUX_PIN) == 0) vTaskDelay(pdMS_TO_TICKS(10));
        
        gpio_set_level(LORA_M0_PIN, 1);
        gpio_set_level(LORA_M1_PIN, 1);
        vTaskDelay(pdMS_TO_TICKS(50));
        while(gpio_get_level(LORA_AUX_PIN) == 0) vTaskDelay(pdMS_TO_TICKS(10));

        uint8_t config_cmd[] = {0xC0, 0x03, 0x03, 0x20, 0x12, 0x83};
        ESP_LOGI("LORA_CONFIG", "Mengirim parameter konfigurasi ke modul...");
        uart_write_bytes(UART_NUM_2, (const char*)config_cmd, sizeof(config_cmd));

        vTaskDelay(pdMS_TO_TICKS(50));
        while(gpio_get_level(LORA_AUX_PIN) == 0) vTaskDelay(pdMS_TO_TICKS(10));

        gpio_set_level(LORA_M0_PIN, 0);
        gpio_set_level(LORA_M1_PIN, 0);
        vTaskDelay(pdMS_TO_TICKS(50));
        while(gpio_get_level(LORA_AUX_PIN) == 0) vTaskDelay(pdMS_TO_TICKS(10));
    }
    ESP_LOGI("LORA_CONFIG", "Konfigurasi selesai! Modul kembali ke Mode Normal.");
}


// Untuk node A hanya nyalakan fungsi uart_lora_init saja
// Untuk node B nyalakan semua fungsi
void init_all_hardware(void) {
    relay_init();
    m0_m1_lora_init();
    aux_lora_init();
    uart_lora_init();
    led_init();
    ESP_LOGI(TAG_HW, "Semua hardware berhasil diinisialisasi.");
}



// ==============================================================================
// KODE KHUSUS NODE A (KAPAL / SLAVE)
// ==============================================================================
#ifdef COMPILE_NODE_A

static const char *TAG = "NODE_A_KAPAL";
SemaphoreHandle_t sensor_mutex;
float current_lat = 0.0;
float current_lon = 0.0;
bool is_gps_valid = false;
float current_radiation = -1.0; 
bool is_using_lora = true; // Status komunikasi awal

// ==============================================================================
// KONFIGURASI WIFI STARLINK & INFLUXDB (NODE A)
// ==============================================================================
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "nvs_flash.h"

// TODO: Ganti dengan SSID dan Password Starlink Kapal
#define WIFI_SSID_STARLINK "STARLINK_KAPAL"   
#define WIFI_PASS_STARLINK "password_starlink" 

// Kredensial InfluxDB (Sudah tanpa precision=s dan menggunakan URL Encoding %20)
#define INFLUX_URL "https://us-east-1-1.aws.cloud2.influxdata.com/api/v2/write?org=Septyo%20Ajie&bucket=DATA1"
#define INFLUX_TOKEN "Token PjX3ONRnhjW2Cn6De06ox12DjKxo_LI2WAfeIy74ioyeZ7ca2AYTB_jwehTd0uPWOfPYjgbFpXgFcNm4TfFsdg=="

static void wifi_event_handler_a(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "WiFi Starlink Terputus. Menghubungkan kembali...");
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "Terhubung ke WiFi Starlink! IP: " IPSTR, IP2STR(&event->ip_info.ip));
    }
}

void wifi_init_starlink(void) {
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler_a, NULL, NULL);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler_a, NULL, NULL);

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID_STARLINK,
            .password = WIFI_PASS_STARLINK,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
}

// ==============================================================================
// FUNGSI UTILITAS SENSOR
// ==============================================================================
float convert_nmea_to_decimal(float nmea_coord, char direction) {
    int degrees = (int)(nmea_coord / 100);
    float minutes = nmea_coord - (degrees * 100);
    float decimal = degrees + (minutes / 60.0);
    if (direction == 'S' || direction == 'W') decimal *= -1.0;
    return decimal;
}

uint16_t crc16(uint8_t *buf, int len) {
    uint16_t crc = 0xFFFF;
    for (int i = 0; i < len; i++) {
        crc ^= buf[i];
        for (int j = 0; j < 8; j++) {
            if (crc & 0x0001) { crc >>= 1; crc ^= 0xA001; }
            else crc >>= 1;
        }
    }
    return crc;
}

// ==============================================================================
// TASK SENSOR (Hardware Asli)
// ==============================================================================
void sensor_reading_task(void *pvParameters) {
    int cycle_count = 0;
    
    while (1) {
        ESP_LOGI(TAG, "--- MULAI SIKLUS PEMBACAAN SENSOR ---");

        // 1. SESI GPS (Setiap Siklus)
        uart_set_pin(GPS_UART_NUM, GPS_TX_PIN_ESP, GPS_RX_PIN_ESP, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
        uart_set_mode(GPS_UART_NUM, UART_MODE_UART);
        vTaskDelay(pdMS_TO_TICKS(50));  
        uart_flush_input(GPS_UART_NUM);

        uint32_t start_time = esp_timer_get_time() / 1000;
        char line[128] = {0};
        int line_pos = 0;
        uint8_t data[64];
        bool got_gps_this_cycle = false;

        while ((esp_timer_get_time() / 1000) - start_time < 3000) {
            int len = uart_read_bytes(GPS_UART_NUM, data, sizeof(data) - 1, pdMS_TO_TICKS(50));
            for (int i = 0; i < len; i++) {
                char c = (char)data[i];
                if (c == '\n') {
                    line[line_pos] = '\0'; 
                    if (strncmp(line, "$GPRMC", 6) == 0) {
                        char *tokens[15];
                        int token_count = 0;
                        char *token = strtok(line, ",");
                        while (token != NULL && token_count < 15) {
                            tokens[token_count++] = token;
                            token = strtok(NULL, ",");
                        }
                        if (token_count > 6 && strcmp(tokens[2], "A") == 0) {
                            float raw_lat = atof(tokens[3]);
                            char lat_dir = tokens[4][0];
                            float raw_lon = atof(tokens[5]);
                            char lon_dir = tokens[6][0];
                            
                            if (xSemaphoreTake(sensor_mutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                                current_lat = convert_nmea_to_decimal(raw_lat, lat_dir);
                                current_lon = convert_nmea_to_decimal(raw_lon, lon_dir);
                                is_gps_valid = true;
                                xSemaphoreGive(sensor_mutex);
                            }
                            got_gps_this_cycle = true;
                        }
                    }
                    line_pos = 0; 
                } else if (c != '\r' && line_pos < sizeof(line) - 1) {
                    line[line_pos++] = c;
                }
            }
            if(got_gps_this_cycle) break; 
        }
        
        if(!got_gps_this_cycle && xSemaphoreTake(sensor_mutex, pdMS_TO_TICKS(10)) == pdTRUE) {
             is_gps_valid = false;
             xSemaphoreGive(sensor_mutex);
        }

        // 2. SESI RS485 RADIASI CAHAYA (Tiap 2 Siklus)
        if (cycle_count % 2 == 0) {
            ESP_LOGI(TAG, "Mengambil alih UART1 untuk RS485 (Auto-Direction)...");
            
            uart_set_pin(GPS_UART_NUM, RS485_TXD_PIN, RS485_RXD_PIN, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
            uart_set_mode(GPS_UART_NUM, UART_MODE_UART);
            vTaskDelay(pdMS_TO_TICKS(50));
            uart_flush_input(GPS_UART_NUM);

            uint8_t req[6] = {0x01, 0x03, 0x00, 0x00, 0x00, 0x01};
            uint16_t crc_req = crc16(req, 6);
            
            uint8_t tx_data[8];
            memcpy(tx_data, req, 6);
            tx_data[6] = crc_req & 0xFF;        
            tx_data[7] = (crc_req >> 8) & 0xFF; 
            
            uart_write_bytes(GPS_UART_NUM, (const char*)tx_data, 8);
            uart_wait_tx_done(GPS_UART_NUM, pdMS_TO_TICKS(100));
            
            uint8_t rx_modbus[16] = {0};
            int rx_len = uart_read_bytes(GPS_UART_NUM, rx_modbus, sizeof(rx_modbus) - 1, pdMS_TO_TICKS(500));
            
            if (rx_len >= 7) {
                uint16_t crc_calc = crc16(rx_modbus, 5);
                uint16_t crc_recv = (rx_modbus[6] << 8) | rx_modbus[5];
                
                if (crc_calc == crc_recv) {
                    int raw_val = (rx_modbus[3] << 8) | rx_modbus[4];
                    if (xSemaphoreTake(sensor_mutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                        current_radiation = raw_val * 1.0;
                        xSemaphoreGive(sensor_mutex);
                    }
                    ESP_LOGI(TAG, "Radiasi Tersimpan: %.1f W/m2", current_radiation);
                } else {
                    ESP_LOGE(TAG, "RS485 CRC Error!");
                }
            } else {
                ESP_LOGE(TAG, "RS485 Timeout / Tidak ada balasan.");
            }
        }

        cycle_count++;
        ESP_LOGI(TAG, "--- SIKLUS SELESAI, TIDUR 15 DETIK ---");
        vTaskDelay(pdMS_TO_TICKS(15000)); 
    }
}

// ==============================================================================
// TASK LORA & HTTP POST
// ==============================================================================
void lora_slave_task(void *pvParameters) {
    char payload[128] = {0};
    uint8_t rx_data[64] = {0};
    uint32_t seq_num = 0;

    uint32_t last_rx_time = esp_timer_get_time() / 1000;
    uint32_t last_influx_publish = 0; 
    
    while (1) {
        uint32_t current_time = esp_timer_get_time() / 1000;

        // FAIL-SAFE: 30 Detik
        if (is_using_lora && (current_time - last_rx_time > 30000)) {
            ESP_LOGE(TAG, "     [FAIL-SAFE] Hilang kontak dengan Pelabuhan > 30 Detik!");
            gpio_set_level(STARLINK_RELAY_PIN, 0); // Relay ON -> Starlink Menyala
            is_using_lora = false;
            last_rx_time = current_time;
        }

        // 1. MENDENGARKAN PERINTAH LORA (Dari Node B Pelabuhan)
        int len = uart_read_bytes(UART_NUM_2, rx_data, sizeof(rx_data) - 1, pdMS_TO_TICKS(200));
        bool force_reply_beacon = false;
        
        if (len > 0) {
            rx_data[len] = '\0';
            last_rx_time = esp_timer_get_time() / 1000; 
            
            if (strstr((char*)rx_data, "CMD:STARLINK") != NULL) {
                if (is_using_lora) {
                    ESP_LOGW(TAG, "     [INSTRUKSI] PINDAH KE STARLINK!");
                    gpio_set_level(STARLINK_RELAY_PIN, 0); 
                    is_using_lora = false; 
                }
            } 
            else if (strstr((char*)rx_data, "CMD:LORA") != NULL) {
                if (!is_using_lora) {
                    ESP_LOGW(TAG, "     [INSTRUKSI] KEMBALI KE LORA!");
                    gpio_set_level(STARLINK_RELAY_PIN, 1); 
                    is_using_lora = true; 
                }
            }
            else if (strstr((char*)rx_data, "ACK") != NULL) { 
                if (!is_using_lora) {
                    ESP_LOGW(TAG, "     [HANDSHAKE] Sinyal Pelabuhan Tertangkap! Mengirim Probe...");
                    force_reply_beacon = true; 
                }
            }
        }

        // 2A. MENGIRIM DATA VIA LORA (Mode Normal)
        if (is_using_lora || force_reply_beacon) {
            seq_num++;
            if (xSemaphoreTake(sensor_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
                if (is_gps_valid) {
                    snprintf(payload, sizeof(payload), "SEQ:%lu,LAT:%.6f,LON:%.6f,RAD:%.1f", (unsigned long)seq_num, current_lat, current_lon, current_radiation);
                } else {
                    snprintf(payload, sizeof(payload), "SEQ:%lu,GPS_NO_FIX,RAD:%.1f", (unsigned long)seq_num, current_radiation);
                }
                xSemaphoreGive(sensor_mutex);
            }
            
            uart_write_bytes(UART_NUM_2, payload, strlen(payload));
            ESP_LOGI(TAG, "=> Mengirim Telemetri (LoRa): %s", payload);
            
            vTaskDelay(pdMS_TO_TICKS(1800));
        } 
        
        // 2B. MENGIRIM DATA VIA STARLINK KE INFLUXDB (HTTP POST)
        if (!is_using_lora) {
            if (current_time - last_influx_publish >= 2000) {
                
                // Hanya kirim jika GPS Fix (Mencegah Null Island 0.0)
                if (xSemaphoreTake(sensor_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
                    if (is_gps_valid) {
                        char line_protocol[512];
                        
                        // Memasukkan current_lat, current_lon, dan current_radiation dari sensor nyata.
                        // Sisanya diisi parameter dummy yang diperlukan Streamlit + \n di akhir teks.
                        snprintf(line_protocol, sizeof(line_protocol), 
                                    "telemetry,node_id=KAPAL_01,antenna_type=with_antenna "
                                    "latitude=%.6f,longitude=%.6f,"
                                    "rssi=-115i,snr=0i,distance_from_gateway=3500i,state=2i,"
                                    "speed=5.8,P_LoRa=0.15,"
                                    "packet_received=100i,packet_sent=100i,wind_speed=6i,"
                                    "active_channel=\"satellite\",weather=\"%.1f W/m2\"\n", 
                                    current_lat, current_lon, current_radiation);
                        
                        esp_http_client_config_t config = {
                            .url = INFLUX_URL,
                            .method = HTTP_METHOD_POST,
                            .transport_type = HTTP_TRANSPORT_OVER_SSL,
                            .crt_bundle_attach = esp_crt_bundle_attach,
                            .timeout_ms = 3000, 
                            .auth_type = HTTP_AUTH_TYPE_NONE, // Mencegah bug 401 Not Supported
                        };
                        
                        esp_http_client_handle_t client = esp_http_client_init(&config);
                        esp_http_client_set_header(client, "Authorization", INFLUX_TOKEN);
                        esp_http_client_set_header(client, "Content-Type", "text/plain; charset=utf-8");
                        esp_http_client_set_post_field(client, line_protocol, strlen(line_protocol));

                        ESP_LOGI(TAG, "Mengirim Sensor Nyata ke InfluxDB via Starlink...");
                        esp_err_t err = esp_http_client_perform(client);
                        
                        if (err == ESP_OK) {
                            ESP_LOGI(TAG, "=> SUCCESS (Status %d): %s", esp_http_client_get_status_code(client), line_protocol);
                        } else {
                            ESP_LOGW(TAG, "=> FAILED HTTP POST: %s", esp_err_to_name(err));
                        }
                        
                        esp_http_client_cleanup(client);
                    } else {
                        ESP_LOGW(TAG, "GPS No Fix, menunda pengiriman InfluxDB...");
                    }
                    xSemaphoreGive(sensor_mutex);
                }
                last_influx_publish = current_time;
            }
            
            if (!force_reply_beacon) {
                vTaskDelay(pdMS_TO_TICKS(100)); 
            }
        }
    }
}

void app_main(void) {
    ESP_LOGW(TAG, "MEMULAI FIRMWARE NODE A (KAPAL - HARDWARE ASLI)");
    sensor_mutex = xSemaphoreCreateMutex();
    
    init_all_hardware();
    relay_init();
    wifi_init_starlink();
    
    // Inisialisasi UART untuk GPS & RS485 Modbus
    uart_config_t uart1_config = {
        .baud_rate = 9600,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_param_config(GPS_UART_NUM, &uart1_config));
    ESP_ERROR_CHECK(uart_driver_install(GPS_UART_NUM, 1024 * 2, 0, 0, NULL, 0));

    // Mengalokasikan stack yang besar karena kebutuhan cJSON / HTTPS Modbus
    xTaskCreate(sensor_reading_task, "sensor_task", 4096, NULL, 4, NULL);
    xTaskCreate(lora_slave_task, "lora_slave", 8192, NULL, 5, NULL); 
}



#elif defined(COMPILE_NODE_B)
// ==============================================================================
// KODE KHUSUS NODE B (PELABUHAN / MASTER)
// ==============================================================================

static const char *TAG = "NODE_B_MASTER";

#define WIFI_SSID "Ppppp"
#define WIFI_PASS "12345654"
#define MQTT_BROKER_URI "mqtt://broker.emqx.io"
#define MQTT_TOPIC_PUB "vms_hybrid_2026/telemetry"
#define MQTT_TOPIC_SUB "vms_hybrid_2026/switching_decision"

int current_noise_floor_dbm = -105;
int noise_retry_count = 0;
const int MAX_NOISE_RETRIES = 5;
int last_valid_rssi_dbm = 0; 
bool is_test_started = false;
bool is_node_a_on_starlink = false;
uint32_t start_time_ms = 0;
uint32_t received_packets = 0;
esp_mqtt_client_handle_t mqtt_client = NULL;

typedef struct {
    int rssi;
    int snr;
    float distance;
    float radiation;
    float pdr;
    unsigned long received_packet;
    unsigned long expected_packet;
    unsigned long packet_loss;
} telemetry_data_t;

QueueHandle_t mqtt_queue;

// FUNGSI UNTUK MENGIRIM PERINTAH SWITCHING KE KAPAL (VIA LORA)
void apply_switching_decision(const char* decision) {
    if (strncmp(decision, "LORA", 4) == 0) {
        ESP_LOGW(TAG, "     [ML DECISION] : Menggunakan LoRa. Mengirim perintah ke Kapal...");
        char cmd[] = "CMD:LORA";
        uart_write_bytes(UART_NUM_2, cmd, strlen(cmd));
        is_node_a_on_starlink = false;
        
    } else if (strncmp(decision, "STARLINK", 8) == 0) {
        ESP_LOGW(TAG, "     [ML DECISION] : Menggunakan Starlink. Mengirim perintah ke Kapal...");
        char cmd[] = "CMD:STARLINK";
        uart_write_bytes(UART_NUM_2, cmd, strlen(cmd));
        is_node_a_on_starlink = true;
    }
}

static void wifi_event_handler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "WiFi Terputus. Menghubungkan kembali...");
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "Terhubung ke WiFi! IP Address: " IPSTR, IP2STR(&event->ip_info.ip));
    }
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    esp_mqtt_event_handle_t event = event_data;
    switch ((esp_mqtt_event_id_t)event_id) {
        case MQTT_EVENT_CONNECTED:
            ESP_LOGI(TAG, "MQTT Terhubung ke HiveMQ!");
            esp_mqtt_client_subscribe(mqtt_client, MQTT_TOPIC_SUB, 0);
            ESP_LOGI(TAG, "Mendengarkan keputusan ML di topik: %s", MQTT_TOPIC_SUB);
            break;
        case MQTT_EVENT_DATA:
            ESP_LOGW(TAG, "     [RECEIVED] KEPUTUSAN ML DITERIMA ");
            printf("    [TOPIC] : %.*s\r\n", event->topic_len, event->topic);
            char decision[16] = {0};
            int len = event->data_len;
            if (len > 15) {
                ESP_LOGE(TAG, "Data Tidak Valid");
                printf("Data yang dikirim : %.*s\r\n", event->data_len, event->data);
            } else if(len > 0 && len <= 15) {
                printf("Data yang dikirim : %.*s\r\n", event->data_len, event->data);
                memcpy(decision, event->data, len);
                apply_switching_decision(decision);
            }
            break;
        case MQTT_EVENT_DISCONNECTED:
            ESP_LOGE(TAG, "MQTT Terputus.");
            break;
        default:
            break;
    }
}

void wifi_mqtt_init(void) {
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL);

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    esp_mqtt_client_config_t mqtt_cfg = {
        .broker.address.uri = MQTT_BROKER_URI,
    };
    mqtt_client = esp_mqtt_client_init(&mqtt_cfg);
    esp_mqtt_client_register_event(mqtt_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL);
    esp_mqtt_client_start(mqtt_client);
}

float calculate_distance(float lat1, float lon1, float lat2, float lon2) {
    float dLat = (lat2 - lat1) * M_PI / 180.0;
    float dLon = (lon2 - lon1) * M_PI / 180.0;
    lat1 = (lat1) * M_PI / 180.0;
    lat2 = (lat2) * M_PI / 180.0;
    float a = pow(sin(dLat / 2), 2) + pow(sin(dLon / 2), 2) * cos(lat1) * cos(lat2);
    float rad = 6371.0; 
    float c = 2 * asin(sqrt(a));
    return rad * c; 
}

void lora_master_task(void *pvParameters) {
    uint8_t data[BUF_SIZE] = {0};
    
    while (1) {
        int len = uart_read_bytes(UART_NUM_2, data, BUF_SIZE - 1, pdMS_TO_TICKS(100));
        
        if (len > 0) {
            if (len == 4 && data[0] == 0xC1) {
                int temp_noise = - (256 - (int)data[3]);
                
                if(abs(temp_noise - last_valid_rssi_dbm) <= 15) {
                    noise_retry_count++;
                    if (noise_retry_count >= MAX_NOISE_RETRIES) {
                        current_noise_floor_dbm = temp_noise;
                        noise_retry_count = 0; 
                    } else {
                        uint8_t query_noise_cmd[] = {0xC0, 0xC1, 0xC2, 0xC3, 0x00, 0x01};
                        uart_write_bytes(UART_NUM_2, (const char*)query_noise_cmd, sizeof(query_noise_cmd));
                    }
                } else {
                    current_noise_floor_dbm = temp_noise;
                    noise_retry_count = 0; 
                    ESP_LOGI(TAG, "     [UPDATE] Update Ambient Noise: %d dBm", current_noise_floor_dbm);
                }
            }
            else if (len > 1) { 
                uint8_t rssi_byte = data[len - 1];
                int rssi_dbm = (int)rssi_byte - 256; 
                int snr_db = rssi_dbm - current_noise_floor_dbm;

                last_valid_rssi_dbm = rssi_dbm;
                data[len - 1] = '\0'; 
                char* payload = (char*)data;

                ESP_LOGI(TAG, "     [PESAN MASUK : %s", payload);
                ESP_LOGI(TAG, "     [RSSI]: %d dBm | [SNR]: %d dB | [Ambient Noise]: %d", rssi_dbm, snr_db, current_noise_floor_dbm);
                
                float ship_lat = 0.0, ship_lon = 0.0, ship_rad = 0.0;
                bool is_valid_packet = false;
                bool has_gps_fix = false;
                uint32_t ship_seq = 0;
                // Parsing Payload yang mengandung LAT, LON, dan RAD
                if (strncmp(payload, "SEQ:", 4) == 0 && strstr(payload, "GPS_NO_FIX") != NULL) {
                    is_valid_packet = true;
                    has_gps_fix = false;
                    sscanf(payload, "SEQ:%lu,GPS_NO_FIX,RAD:%f", &ship_seq, &ship_rad); 
                } 
                else if (sscanf(payload, "SEQ:%lu,LAT:%f,LON:%f,RAD:%f", &ship_seq, &ship_lat, &ship_lon, &ship_rad) == 4) {
                    is_valid_packet = true;
                    has_gps_fix = true;
                }

                if (is_valid_packet) {
                    received_packets++;
                    
                    // expected_packets adalah angka SEQ tertinggi yang pernah diterima
                    uint32_t expected_packets = ship_seq; 
                    
                    uint32_t packet_loss = 0;
                    if (expected_packets > received_packets) {
                        packet_loss = expected_packets - received_packets;
                    }
                    
                    float pdr = ((float)received_packets / expected_packets) * 100.0;
                    
                    ESP_LOGW(TAG, "     [EVALUASI] PDR: %.1f%% | Loss: %lu | Diterima: %lu/%lu", pdr, packet_loss, received_packets, expected_packets);
                    ESP_LOGI(TAG, "     [SENSOR] Radiasi Cahaya: %.1f W/m2", ship_rad);

                    if (has_gps_fix) {
                        float distance = calculate_distance(BASE_LAT, BASE_LON, ship_lat, ship_lon);
                        ESP_LOGI(TAG, "     [SPASIAL] Jarak: %.3f KM", distance);
                        ESP_LOGI(TAG, "     [Longitude] : %.6f Latitude : %.6f", ship_lon, ship_lat);

                        telemetry_data_t payload_to_ml = {
                            .rssi = rssi_dbm,
                            .snr = snr_db,
                            .distance = distance,
                            .radiation = ship_rad, // Masukkan ke queue
                            .pdr = pdr,
                            .received_packet = received_packets,
                            .expected_packet = expected_packets,
                            .packet_loss = packet_loss
                        };

                        if (xQueueSend(mqtt_queue, &payload_to_ml, 0) != pdPASS) {
                            ESP_LOGW(TAG, "Antrean MQTT penuh, paket dibuang.");
                        }
                    } else {
                        ESP_LOGW(TAG, "    [SPASIAL] Kapal belum mendapat sinyal GPS.");
                    }

                    if(GREEN_LED_PIN != -1) {
                        gpio_set_level(GREEN_LED_PIN, 1);
                        vTaskDelay(pdMS_TO_TICKS(50));
                        gpio_set_level(GREEN_LED_PIN, 0);
                    }
                }
                else {
                    ESP_LOGE(TAG, "Bukan Data yang Diharapkan");
                    if(RED_LED_PIN != -1) {
                        gpio_set_level(RED_LED_PIN, 1);
                        vTaskDelay(pdMS_TO_TICKS(50));
                        gpio_set_level(RED_LED_PIN, 0);
                    }
                }
            }
        }
    }
}

void noise_reading_task(void *pvParameters) {
    uint8_t query_noise_cmd[] = {0xC0, 0xC1, 0xC2, 0xC3, 0x00, 0x01};
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(15000));
        ESP_LOGI(TAG, "     [REQUEST] Meminta Update Ambient Noise ");
        uart_write_bytes(UART_NUM_2, (const char*)query_noise_cmd, sizeof(query_noise_cmd));
    }
}

void mqtt_publish_task(void *pvParameters) {
    telemetry_data_t out_data;
    while (1) {
        if (xQueueReceive(mqtt_queue, &out_data, portMAX_DELAY)) {
            if (mqtt_client != NULL) {
                cJSON *root = cJSON_CreateObject();
                cJSON_AddNumberToObject(root, "rssi", out_data.rssi);
                cJSON_AddNumberToObject(root, "snr", out_data.snr);
                cJSON_AddNumberToObject(root, "distance_km", out_data.distance);
                cJSON_AddNumberToObject(root, "radiation_wm2", out_data.radiation); // Dikirim ke ML
                cJSON_AddNumberToObject(root, "pdr_percent", out_data.pdr);
                cJSON_AddNumberToObject(root, "received_packet", out_data.received_packet);
                cJSON_AddNumberToObject(root, "expected_packet", out_data.expected_packet);
                cJSON_AddNumberToObject(root, "packet_loss", out_data.packet_loss);
                
                char *json_string = cJSON_PrintUnformatted(root);
                int msg_id = esp_mqtt_client_publish(mqtt_client, MQTT_TOPIC_PUB, json_string, 0, 1, 0);
                
                if (msg_id != -1) {
                    ESP_LOGI(TAG, "     [MQTT Sent]: %s", json_string);
                } else {
                    ESP_LOGE(TAG, "Gagal kirim MQTT (Broker Down/Disconnect)");
                }
                
                cJSON_Delete(root);
                free(json_string);
            }
        }
    }
}

void heartbeat_broadcast_task(void *pvParameters) {
    char ack_msg[] = "ACK";
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(10000)); 
        uart_write_bytes(UART_NUM_2, ack_msg, strlen(ack_msg)); 
        ESP_LOGI(TAG, "     [TX] Memancarkan sinyal Handshake (ACK)...");
    }
}

void app_main(void) {
    ESP_LOGW(TAG, "MEMULAI FIRMWARE NODE B (PELABUHAN)");

    mqtt_queue = xQueueCreate(10, sizeof(telemetry_data_t));
    wifi_mqtt_init();
    init_all_hardware();
    configure_lora_channel();
    
    xTaskCreate(lora_master_task, "lora_master", 4096, NULL, 5, NULL);
    xTaskCreate(noise_reading_task, "noise_task", 4096, NULL, 4, NULL);
    xTaskCreate(mqtt_publish_task, "mqtt_pub", 8192, NULL, 3, NULL);
    xTaskCreate(heartbeat_broadcast_task, "ack_task", 4096, NULL, 6, NULL);
}

#endif