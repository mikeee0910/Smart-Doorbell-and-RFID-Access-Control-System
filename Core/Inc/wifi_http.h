#ifndef WIFI_HTTP_H
#define WIFI_HTTP_H

#include <stdint.h>

#define WIFI_SSID          "Meng"
#define WIFI_PASSWORD      "11112222"

/* RPi server IP — change this to your Raspberry Pi's IP */
#define SERVER_IP_0        172
#define SERVER_IP_1        20
#define SERVER_IP_2        10
#define SERVER_IP_3        4
#define SERVER_PORT        5001

typedef enum {
    WIFI_HTTP_OK = 0,
    WIFI_HTTP_CONNECT_FAIL,
    WIFI_HTTP_SEND_FAIL,
    WIFI_HTTP_RECV_FAIL
} WiFi_HTTP_Status_t;

int  WiFi_HTTP_Init(void);
int  WiFi_HTTP_PostRFID(const uint8_t uid[4], uint8_t *unlock);
int  WiFi_HTTP_PostDoorbell(void);

#endif /* WIFI_HTTP_H */
