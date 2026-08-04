// ws_client — WiFi 连接 + 后端 /ws/device WebSocket 客户端。
// WiFi 例程 hello 中不存在（Emerald-hello 只有 OLED init，无 WiFi 代码），
// 这里用标准 ESP32 Arduino WiFi.h STA 连接写法，未照抄任何示例。
#pragma once

#include <Arduino.h>

// 连接状态，供 display 模块渲染「离线/重连中」。
enum class ConnState {
    WIFI_CONNECTING,
    WS_CONNECTING,
    ONLINE,
};

void wsClientSetup();
void wsClientLoop();
ConnState wsClientState();

// 上行：回 pong / ack。
void wsSendPong();
void wsSendAck(const String &msgId, bool ok, const char *error = nullptr);
