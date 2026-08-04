#include "ws_client.h"

#include <ArduinoJson.h>
#include <WebSocketsClient.h>
#include <WiFi.h>

#include "display.h"
#include "secrets.h"

namespace {

WebSocketsClient webSocket;
ConnState state = ConnState::WIFI_CONNECTING;

// WiFi 重连退避：1s → 2s → ... → 30s 上限。
unsigned long wifiBackoffMs = 1000;
unsigned long wifiLastAttempt = 0;
const unsigned long kBackoffCapMs = 30000;

// WS 重连退避：同样 1s → ... → 30s；连上后各自复位。
unsigned long wsBackoffMs = 1000;
unsigned long wsLastAttempt = 0;
bool wsBeginPending = false;

void resetWifiBackoff() { wifiBackoffMs = 1000; }
void resetWsBackoff() { wsBackoffMs = 1000; }

void beginWsConnection() {
    static char authHeader[96];
    snprintf(authHeader, sizeof(authHeader), "Authorization: Bearer %s", AUTH_TOKEN);
    webSocket.setExtraHeaders(authHeader);
    webSocket.begin(BACKEND_HOST, BACKEND_PORT, BACKEND_PATH);
    wsLastAttempt = millis();
}

void handleTextMessage(const uint8_t *payload, size_t length) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) {
        Serial.printf("[ws] JSON 解析失败: %s\n", err.c_str());
        return;
    }
    const char *type = doc["type"] | "";
    const char *msgIdRaw = doc["msg_id"] | "";
    String msgId(msgIdRaw);

    if (strcmp(type, "hello_ack") == 0) {
        Serial.println("[ws] hello_ack 收到");
    } else if (strcmp(type, "ping") == 0) {
        wsSendPong();
    } else if (strcmp(type, "message_stream_start") == 0) {
        displayStreamStart(msgId);
    } else if (strcmp(type, "message_stream_delta") == 0) {
        const char *delta = doc["delta"] | "";
        displayStreamDelta(msgId, String(delta));
    } else if (strcmp(type, "message_stream_end") == 0) {
        displayStreamEnd(msgId);
    } else if (strcmp(type, "message_segments") == 0) {
        const char *content = doc["content"] | "";
        displaySegments(msgId, String(content));
    } else if (strcmp(type, "channel_message") == 0) {
        const char *content = doc["content"] | "";
        displayChannelMessage(msgId, String(content));
    } else if (strcmp(type, "action") == 0) {
        const char *actionType = doc["action"]["type"] | "";
        if (strcmp(actionType, "show_heart") == 0) {
            int durationMs = doc["action"]["duration_ms"] | 4000;
            wsSendAck(msgId, true);
            displayShowHeart(durationMs);
        } else {
            wsSendAck(msgId, false, "unsupported action type");
        }
    }
    // group_round_start/end、其余类型本单忽略。
}

void onWsEvent(WStype_t type, uint8_t *payload, size_t length) {
    switch (type) {
        case WStype_CONNECTED: {
            state = ConnState::ONLINE;
            resetWsBackoff();
            displaySetConnState(state);
            Serial.println("[ws] 已连接，发送 hello");
            JsonDocument hello;
            hello["type"] = "hello";
            String out;
            serializeJson(hello, out);
            webSocket.sendTXT(out);
            break;
        }
        case WStype_DISCONNECTED:
            state = ConnState::WS_CONNECTING;
            displaySetConnState(state);
            Serial.println("[ws] 断开，等待退避重连");
            break;
        case WStype_TEXT:
            handleTextMessage(payload, length);
            break;
        default:
            break;
    }
}

}  // namespace

void wsClientSetup() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    state = ConnState::WIFI_CONNECTING;
    webSocket.onEvent(onWsEvent);
    // 关闭库内置固定间隔重连，改由本文件的指数退避手动驱动 begin()，
    // 避免两套重连逻辑互相打架。
    webSocket.setReconnectInterval(kBackoffCapMs);
}

void wsClientLoop() {
    if (WiFi.status() != WL_CONNECTED) {
        if (state != ConnState::WIFI_CONNECTING) {
            state = ConnState::WIFI_CONNECTING;
            displaySetConnState(state);
        }
        unsigned long now = millis();
        if (now - wifiLastAttempt >= wifiBackoffMs) {
            wifiLastAttempt = now;
            WiFi.disconnect();
            WiFi.begin(WIFI_SSID, WIFI_PASS);
            wifiBackoffMs = min(wifiBackoffMs * 2, kBackoffCapMs);
            Serial.printf("[wifi] 重连中，下次退避 %lums\n", wifiBackoffMs);
        }
        return;
    }
    if (WiFi.status() == WL_CONNECTED && wifiBackoffMs != 1000) {
        resetWifiBackoff();
    }

    if (state == ConnState::WIFI_CONNECTING) {
        // WiFi 刚连上：切到 WS_CONNECTING，立即发起第一次 WS 连接。
        state = ConnState::WS_CONNECTING;
        displaySetConnState(state);
        beginWsConnection();
    } else if (state == ConnState::WS_CONNECTING) {
        unsigned long now = millis();
        if (now - wsLastAttempt >= wsBackoffMs) {
            beginWsConnection();
            wsBackoffMs = min(wsBackoffMs * 2, kBackoffCapMs);
            Serial.printf("[ws] 重连中，下次退避 %lums\n", wsBackoffMs);
        }
    }

    webSocket.loop();
}

ConnState wsClientState() { return state; }

void wsSendPong() {
    JsonDocument doc;
    doc["type"] = "pong";
    String out;
    serializeJson(doc, out);
    webSocket.sendTXT(out);
}

void wsSendAck(const String &msgId, bool ok, const char *error) {
    JsonDocument doc;
    doc["type"] = "ack";
    doc["msg_id"] = msgId;
    doc["ok"] = ok;
    if (!ok && error != nullptr) {
        doc["error"] = error;
    }
    String out;
    serializeJson(doc, out);
    webSocket.sendTXT(out);
}
