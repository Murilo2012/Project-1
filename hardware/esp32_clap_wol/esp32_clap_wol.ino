/*
 * APEX — detector de palmas com Wake-on-LAN
 *
 * O PROBLEMA QUE ISSO RESOLVE
 * Com o PC desligado, nenhum software roda pra ouvir as palmas. É por isso que
 * "bate palma e o PC liga" nos vídeos é quase sempre suspensão (não desligado)
 * ou edição. Este ESP32 fica ligado 24h consumindo ~1W, ouve o tempo todo, e
 * quando reconhece o padrão manda um magic packet que acorda o PC de verdade.
 *
 * O QUE VOCÊ PRECISA
 *   - ESP32 (qualquer um com WiFi)           ~R$ 40
 *   - Microfone I2S INMP441 ou módulo KY-038 ~R$ 15
 *   - Fonte USB 5V
 *
 * LIGAÇÃO (INMP441, I2S)
 *   VDD -> 3V3     GND -> GND     L/R -> GND
 *   SCK -> GPIO14  WS  -> GPIO15  SD  -> GPIO32
 *
 * ANTES DE FUNCIONAR, NA BIOS E NO WINDOWS
 *   1. BIOS: ative "Wake on LAN" / "Power On By PCI-E". Sem isso, nada disso
 *      funciona — a placa de rede fica sem energia com o PC desligado.
 *   2. Windows: Gerenciador de Dispositivos > sua placa de rede >
 *      Propriedades > Gerenciamento de Energia > marque "Permitir que este
 *      dispositivo reative o computador" e "Somente com o Magic Packet".
 *   3. Desative a Inicialização Rápida do Windows: painel de controle >
 *      opções de energia > escolher a função dos botões > desmarcar
 *      "Ligar inicialização rápida". Ela desliga a NIC de vez.
 *   4. WoL funciona por cabo. Em WiFi, quase nunca.
 *
 * DESCOBRIR O SEU MAC: no PowerShell, `getmac /v`
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <driver/i2s.h>

// ---------------------------------------------------------------- CONFIG ---

const char* WIFI_SSID     = "SUA_REDE";
const char* WIFI_PASSWORD = "SUA_SENHA";

// MAC da placa de rede do PC que você quer acordar.
uint8_t TARGET_MAC[6] = { 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF };

const IPAddress BROADCAST_IP(255, 255, 255, 255);
const uint16_t  WOL_PORT = 9;

// Detecção de palmas. Ajuste THRESHOLD se der falso positivo ou não pegar.
const int      CLAPS_NEEDED       = 2;
const uint32_t MIN_GAP_MS         = 120;    // mais rápido que isso é ruído
const uint32_t MAX_GAP_MS         = 900;    // mais lento que isso são palmas soltas
const uint32_t REFRACTORY_MS      = 150;    // ignora o eco da mesma palma
const uint32_t COOLDOWN_MS        = 10000;  // não acorda o PC duas vezes seguidas
const float    THRESHOLD_ABOVE_FLOOR = 3.0; // múltiplo do piso de ruído

// Pinos I2S
#define I2S_SCK 14
#define I2S_WS  15
#define I2S_SD  32
#define I2S_PORT I2S_NUM_0

const int SAMPLE_RATE = 16000;
const int BUFFER_LEN  = 512;

// ----------------------------------------------------------------- ESTADO ---

WiFiUDP udp;
int32_t samples[BUFFER_LEN];

float    noiseFloor    = 0;
bool     calibrated    = false;
uint32_t clapTimes[8];
int      clapCount     = 0;
uint32_t lastPeakMs    = 0;
uint32_t lastTriggerMs = 0;

// ------------------------------------------------------------------ SETUP ---

void setupI2S() {
  i2s_config_t config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 4,
    .dma_buf_len = BUFFER_LEN,
    .use_apll = false
  };
  i2s_pin_config_t pins = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD
  };
  i2s_driver_install(I2S_PORT, &config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pins);
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Conectando ao WiFi");
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Conectado. IP do ESP32: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("Falhou. Vou tentar de novo no loop.");
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nAPEX — detector de palmas");
  setupI2S();
  connectWiFi();
  udp.begin(WOL_PORT);
  Serial.println("Calibrando ruído — silêncio por 3 segundos...");
}

// ------------------------------------------------------------------- WOL ---

void sendMagicPacket() {
  // Magic packet: 6 bytes 0xFF seguidos do MAC repetido 16 vezes.
  uint8_t packet[102];
  memset(packet, 0xFF, 6);
  for (int i = 0; i < 16; i++) {
    memcpy(&packet[6 + i * 6], TARGET_MAC, 6);
  }

  // Manda três vezes: UDP não garante entrega, e este é o pacote que importa.
  for (int attempt = 0; attempt < 3; attempt++) {
    udp.beginPacket(BROADCAST_IP, WOL_PORT);
    udp.write(packet, sizeof(packet));
    udp.endPacket();
    delay(60);
  }
  Serial.println(">>> MAGIC PACKET ENVIADO");
}

// -------------------------------------------------------------- DETECÇÃO ---

float readLevel() {
  size_t bytesRead = 0;
  i2s_read(I2S_PORT, samples, sizeof(samples), &bytesRead, portMAX_DELAY);
  int count = bytesRead / sizeof(int32_t);
  if (count == 0) return 0;

  double sum = 0;
  for (int i = 0; i < count; i++) {
    double value = (double)(samples[i] >> 14);  // INMP441 usa 24 bits úteis
    sum += value * value;
  }
  return sqrt(sum / count);
}

void resetClaps() {
  clapCount = 0;
}

void registerPeak(uint32_t now) {
  if (clapCount > 0) {
    uint32_t gap = now - clapTimes[clapCount - 1];
    if (gap > MAX_GAP_MS) {
      // Muito espaçado: essa palma vira a primeira de uma sequência nova.
      clapCount = 0;
    } else if (gap < MIN_GAP_MS) {
      return;  // eco, ignora
    }
  }

  if (clapCount < 8) {
    clapTimes[clapCount++] = now;
  }

  if (clapCount >= CLAPS_NEEDED) {
    Serial.printf("%d palmas detectadas\n", clapCount);
    if (now - lastTriggerMs > COOLDOWN_MS) {
      lastTriggerMs = now;
      sendMagicPacket();
    } else {
      Serial.println("(em cooldown, não enviei)");
    }
    resetClaps();
  }
}

// ------------------------------------------------------------------- LOOP ---

void loop() {
  static uint32_t calibrationStart = 0;
  static double   calibrationSum = 0;
  static int      calibrationCount = 0;

  float level = readLevel();
  uint32_t now = millis();

  if (!calibrated) {
    if (calibrationStart == 0) calibrationStart = now;
    calibrationSum += level;
    calibrationCount++;
    if (now - calibrationStart > 3000) {
      noiseFloor = calibrationSum / max(calibrationCount, 1);
      if (noiseFloor < 1) noiseFloor = 1;
      calibrated = true;
      Serial.printf("Piso de ruído: %.0f. Pronto — bate palma.\n", noiseFloor);
    }
    return;
  }

  // Piso adaptativo lento: acompanha o ambiente sem seguir as palmas.
  if (level < noiseFloor * 2.0) {
    noiseFloor = noiseFloor * 0.999 + level * 0.001;
  }

  if (level > noiseFloor * THRESHOLD_ABOVE_FLOOR && now - lastPeakMs > REFRACTORY_MS) {
    lastPeakMs = now;
    registerPeak(now);
  }

  // Sequência incompleta que envelheceu: descarta.
  if (clapCount > 0 && now - clapTimes[clapCount - 1] > MAX_GAP_MS) {
    resetClaps();
  }

  if (WiFi.status() != WL_CONNECTED) {
    static uint32_t lastRetry = 0;
    if (now - lastRetry > 30000) {
      lastRetry = now;
      connectWiFi();
    }
  }
}
