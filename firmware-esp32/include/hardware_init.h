#ifndef HARDWARE_INIT_H
#define HARDWARE_INIT_H

#include <stdint.h>

// Definisi COMPILE_MINSIS atau COMPILE_BREADBOARD sekarang 
// diatur otomatis oleh platformio.ini (build_flags)

#ifdef COMPILE_MINSIS

// --- KONFIGURASI PIN (MINSIS CUSTOM) ---
#define LORA_UART_NUM      2 
#define LORA_TXD_PIN       26   
#define LORA_RXD_PIN       27 
#define LORA_M0_PIN        -1   
#define LORA_M1_PIN        -1   
#define LORA_AUX_PIN       -1   
#define GPS_UART_NUM       1 
#define GPS_RX_PIN_ESP     16   
#define GPS_TX_PIN_ESP     17   
#define GREEN_LED_PIN      -1   
#define RED_LED_PIN        -1   
#define BUTTON_PIN         -1
#define RS485_TXD_PIN       13
#define RS485_RXD_PIN       14
#define STARLINK_RELAY_PIN 22

#elif defined(COMPILE_BREADBOARD)

// --- KONFIGURASI PIN (BREADBOARD) ---
#define LORA_UART_NUM      2 
#define LORA_TXD_PIN       17 
#define LORA_RXD_PIN       16 
#define LORA_M0_PIN        23
#define LORA_M1_PIN        22
#define LORA_AUX_PIN       4   
#define GREEN_LED_PIN      32
#define RED_LED_PIN        33
#define BUTTON_PIN         -1
#define STARLINK_RELAY_PIN 25 // Gunakan IO25 atau pin kosong lainnya

#endif

// --- KONFIGURASI UART ---
#define LORA_BAUD_RATE     9600
#define BUF_SIZE           (1024)

// --- DEKLARASI FUNGSI ---
void relay_init(void);
void button_init(void);
void led_init(void);
void m0_m1_lora_init(void);
void aux_lora_init(void);
void uart_lora_init(void);
void init_all_hardware(void); 
void configure_lora_channel(void);

#endif // HARDWARE_INIT_H