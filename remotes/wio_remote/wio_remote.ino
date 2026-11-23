// Wio Terminal remote for the Alvik: drive with the 5-way stick, buttons on top for lights, turbo
// and dance, and a little radar screen of what the robot senses. It talks to the robot's purple
// "phone remote" mode over Bluetooth LE, with the same packets as the web remote (alvik_packets.h),
// so the robot needs no new code.
//
// Controls (screen side up, buttons along the top edge):
//   5-way up / down     forward / back (held)
//   5-way left / right  spin left / right; with up or down held in tilt mode, it curves instead
//   top buttons         left = lights, middle = turbo, right = dance
//   5-way press         nothing by itself (a child's thumb clicks it all the time while driving)
// Grown-up switches: press the stick in and keep it in, then hold a top button for 1.5 s:
//   left = bumper on / off, right = tilt steering on / off. The screen shows which and how long.
//   Both start off each time (BUMPER_AT_START below; the robot itself starts with its bumper on).
//   The logic is in wio_buttons.h, tested on a computer (tests/test_robot.py WioButtons).
//
// It has driven a real Alvik. See README.md next to this file for setup and what is still unchecked.

// Bluetooth first: TFT_eSPI defines min/max macros that break the C++ headers rpcBLE pulls in.
#include "rpcBLEDevice.h"
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <TFT_eSPI.h>
#include "LIS3DHTR.h"
#include "alvik_packets.h"
#include "wio_buttons.h"

// ---------- tweakables ----------
static const char* ROBOT_NAME = "Alvik";
static const int STICK = 100;                // how hard the 5-way pushes, of 100 (the robot scales it to its speed)
static const int CURVE = 60;                 // tilt steering at full tilt, of 100, while driving
static const float TILT_FULL_DEG = 35;       // this much tilt = full steering
static const float TILT_DEAD_DEG = 6;        // less than this = straight
#define TILT_AXIS getAccelerationY           // which way the Wio tilts for steering: check on the screen,
static const float TILT_SIGN = 1;            //   the tilt bar should lean the way you tip it (else -1 / other axis)
static const uint32_t RESEND_MS = 150;       // repeat the stick this often while it is held (robot stops after 600 ms quiet)
static const uint32_t HOLD_MS = 1500;       // grown-up switches: stick pressed in + a top button held this long
static const bool BUMPER_AT_START = false;   // the bumper when the Wio connects. The robot starts every connection
                                             //   with it on, so false = the Wio switches it off straight away
static const uint32_t DRAW_MS = 80;
// top buttons, left to right as you hold it, and the robot button each one presses (1 lights, 2 turbo, 3 dance)
// (if they come out in the wrong order on your Wio, swap the pins here)
static const int TOP_PINS[3] = {WIO_KEY_C, WIO_KEY_B, WIO_KEY_A};
static const int TOP_ROBOT[3] = {1, 2, 3};
static const char* TOP_LABEL[3] = {"Lights", "Turbo", "Dance"};
// the grown-up switch behind each top button (stick pressed in, button held), and its name on the screen
enum { NO_SWITCH, BUMPER_SWITCH, TILT_SWITCH };
static const int TOP_SWITCH[3] = {BUMPER_SWITCH, NO_SWITCH, TILT_SWITCH};
static const char* TOP_SWITCH_LABEL[3] = {"Bumper", "", "Tilt"};
// the robot's numbers, copied from src/remote_control.py (bumper) and docs/pretend.js (ZONE_DEG)
static const int SLOW_CM = 12, BUMPER_CM = 8;
static const float ZONE_DEG[5] = {22.5, 7.5, 0, -7.5, -22.5};   // left is positive

// ---------- Bluetooth ----------
static BLEUUID NUS("6e400001-b5a3-f393-e0a9-e50e24dcca9e");
static BLEUUID NUS_RX("6e400002-b5a3-f393-e0a9-e50e24dcca9e");   // we write here
static BLEUUID NUS_TX("6e400003-b5a3-f393-e0a9-e50e24dcca9e");   // the robot notifies here
static BLEClient* client = nullptr;
static BLERemoteCharacteristic* rx = nullptr;
static BLEAddress* robotAddr = nullptr;
static T_GAP_REMOTE_ADDR_TYPE robotAddrType;
static volatile bool linkUp = false;
static int failures = 0;
static bool waitingShown = false;

// notifications land here (Bluetooth's own task); loop() reads them out
static volatile uint8_t ring[256];
static volatile uint16_t ringHead = 0, ringTail = 0;
static void onNotify(BLERemoteCharacteristic*, uint8_t* data, size_t n, bool) {
  for (size_t i = 0; i < n; i++) {
    uint16_t next = (ringHead + 1) & 255;
    if (next == ringTail) return;            // full: drop the rest (loop() will catch up)
    ring[ringHead] = data[i];
    ringHead = next;
  }
}
class Link : public BLEClientCallbacks {
  void onConnect(BLEClient*) {}
  void onDisconnect(BLEClient*) { linkUp = false; }
};

// ---------- state ----------
static TFT_eSPI tft;
static TFT_eSprite radar(&tft), panel(&tft);
static LIS3DHTR<TwoWire> lis;
static alvik::Reader reader;
static uint32_t lastT = 0, lastS = 0, lastU = 0, askedAt = 0;
static int sentX = 0, sentY = 0;
static uint32_t sentAt = 0;
static bool tilt = false;
static bool bumperSettled = false;           // this connection: the bumper has been put the way BUMPER_AT_START says
static int bumperAsks = 0;
static uint32_t bumperAskedAt = 0;
static float tiltDeg = 0;
static alvik::TopButtons tops(HOLD_MS);
static bool shift = false;                   // the stick is pressed in (and not pushed any way): grown-up switches
static uint32_t drawnAt = 0;
static bool dirty = true;
static int zoneHist[5][3];                   // the last three raw readings per zone, newest first
static const int RW = 200, RH = 214, PW = 120;   // radar and side panel sizes (8-bit sprites: about 66 KB together)

// Write without response, like the web page. Not rx->writeValue(): rpcBLE 1.0.0 always writes
// with response and waits for the answer, whatever you ask for.
static void write(const uint8_t* p, size_t n) {
  if (client && rx) client_attr_write(client->getConnId(), client->getGattcIf(), GATT_WRITE_TYPE_CMD,
                                      rx->getHandle(), n, (uint8_t*)p);
}
static void send(const uint8_t* p, size_t n) {
  if (linkUp) write(p, n);
}

// ---------- connecting ----------
static void dbg(const char* fmt, ...);
static bool findRobot() {
  BLEScan* scan = BLEDevice::getScan();
  scan->setActiveScan(true);
  dbg("scanning");
  BLEScanResults found = scan->start(2, false);
  int named = -1;
  for (int i = 0; i < found.getCount(); i++) if (found.getDevice(i).getName() == ROBOT_NAME) named = i;
  dbg("scan: %d devices, Alvik %s", found.getCount(), named >= 0 ? "seen" : "not seen");
  for (int i = 0; i < found.getCount(); i++) {
    BLEAdvertisedDevice d = found.getDevice(i);
    if (d.getName() == ROBOT_NAME || d.isAdvertisingService(NUS)) {
      delete robotAddr;
      robotAddr = new BLEAddress(d.getAddress());
      robotAddrType = d.getAddressType();
      if (!client) {
        client = BLEDevice::createClient();
        client->setClientCallbacks(new Link());
        static BLEAdvertisedDevice first;              // the first connect sets the client up
        first = d;
        dbg("connecting (first)");
        bool ok = client->connect(&first);
        dbg("connect: %s", ok ? "ok" : "failed");
        return ok;
      }
      dbg("connecting");
      bool ok = client->connect(*robotAddr, robotAddrType);
      dbg("connect: %s", ok ? "ok" : "failed");
      return ok;
    }
  }
  return false;
}

// Which Nordic UART part a UUID is: 1 service, 2 RX, 3 TX, 0 none. Seeed's rpcBLE (1.0.0) builds
// discovered 128-bit UUIDs so that toString() says "<NULL>" (and a lookup by UUID never matches),
// so look at the raw bytes, either way round. 6E40000x-B5A3-F393-E0A9-E50E24DCCA9E.
static int nusPart(BLEUUID u) {
  if (u.length() != 16) return 0;
  const uint8_t* b = u.dataNative();
  if (b[15] == 0x6E && b[14] == 0x40 && b[13] == 0x00 && b[0] == 0x9E) return b[12];   // LSB first
  if (b[0] == 0x6E && b[1] == 0x40 && b[2] == 0x00 && b[15] == 0x9E) return b[3];      // MSB first
  return 0;
}

static bool hookUp() {
  // Read the service list once per connection and never again. rpcBLE frees the old list while its
  // Bluetooth task may still be walking it, and it deletes each characteristic twice when it
  // rebuilds them (both found on a real Wio: "ASSERT: vPortFree").
  dbg("reading services");
  auto* services = client->getServices();
  delay(100);                                // let the Bluetooth task finish with the list
  BLERemoteService* uart = nullptr;
  for (auto& s : *services) {
    int part = nusPart(s.second->getUUID());
    dbg("service %d bytes, nus %d", s.second->getUUID().length(), part);
    if (part == 1) uart = s.second;
  }
  BLERemoteCharacteristic* tx = nullptr;
  rx = nullptr;
  if (uart) {
    // by handle: the by-name list keys every 128-bit one "<NULL>", so they overwrite each other.
    // Read once: asking again would free them twice.
    auto* chars = uart->getCharacteristicsByHandle();
    for (auto& c : *chars) {
      int part = nusPart(c.second->getUUID());
      if (part == 2) rx = c.second;
      if (part == 3) tx = c.second;
    }
    for (auto& c : *chars) {                 // by UUID failed: go by what each one can do
      if (!tx && c.second->canNotify()) tx = c.second;
      if (!rx && (c.second->canWriteNoResponse() || c.second->canWrite())) rx = c.second;
    }
  }
  dbg("hook up: uart %d rx %d tx %d", uart != nullptr, rx != nullptr, tx != nullptr);
  if (!rx || !tx) { client->disconnect(); return false; }   // let the robot advertise again
  // Ask for telemetry first: rpcBLE's registerForNotify() waits, with no time limit, until the first
  // notification arrives, and the robot only sends once asked (it notifies without checking the
  // subscription). Asked the other way round, the Wio hung here for ever.
  uint8_t p[5];
  alvik::joystickPacket(p, 0, 0); write(p, 5);         // start from standing still
  alvik::telemetryRequest(p, true); write(p, 5);
  ringTail = ringHead;                       // nothing left over from the last connection
  bumperSettled = false;
  bumperAsks = 0;
  dbg("asked for telemetry, subscribing");
  tx->registerForNotify(onNotify);
  dbg("subscribed");
  linkUp = true;
  askedAt = millis();
  sentX = sentY = 0;
  return true;
}

// The bumper at the start of a connection. Called on each telemetry packet: once the robot has said
// how its bumper stands, press its bumper button if that isn't how the Wio starts (BUMPER_AT_START),
// and again a second later if that got lost (three tries). After that it is left alone, so the
// grown-up switch stays in charge.
static void startBumper(uint32_t now) {
  if (bumperSettled) return;
  if (reader.t.bumper == BUMPER_AT_START || bumperAsks >= 3) {
    bumperSettled = true;
    dbg("bumper: robot says %s after %d asks", reader.t.bumper ? "on" : "off", bumperAsks);   // USB serial only by now
    return;
  }
  if (bumperAsks && now - bumperAskedAt < 1000) return;
  uint8_t p[5];
  alvik::buttonPacket(p, 4, true); send(p, 5);
  alvik::buttonPacket(p, 4, false); send(p, 5);
  bumperAsks++;
  bumperAskedAt = now;
}

// ---------- input ----------
static void readInput() {
  bool up = !digitalRead(WIO_5S_UP), down = !digitalRead(WIO_5S_DOWN);
  bool left = !digitalRead(WIO_5S_LEFT), right = !digitalRead(WIO_5S_RIGHT);
  bool press = !digitalRead(WIO_5S_PRESS);
  uint32_t now = millis();
  uint8_t p[5];

  // Pressing the stick in does nothing by itself. Pressed in and not pushed any way, it turns the
  // top buttons into the grown-up switches while they are held (wio_buttons.h).
  bool wasShift = shift;
  shift = press && !up && !down && !left && !right;
  bool raw[3];
  alvik::TopButtons::What did[3];
  for (int i = 0; i < 3; i++) raw[i] = !digitalRead(TOP_PINS[i]);
  tops.step(shift, raw, now, did);
  for (int i = 0; i < 3; i++) {
    if (did[i] == alvik::TopButtons::DOWN || did[i] == alvik::TopButtons::TAP) { alvik::buttonPacket(p, TOP_ROBOT[i], true); send(p, 5); }
    if (did[i] == alvik::TopButtons::UP || did[i] == alvik::TopButtons::TAP) { alvik::buttonPacket(p, TOP_ROBOT[i], false); send(p, 5); }
    if (did[i] == alvik::TopButtons::HELD) {
      if (TOP_SWITCH[i] == TILT_SWITCH) tilt = !tilt;
      if (TOP_SWITCH[i] == BUMPER_SWITCH) {           // the robot's button 4; it says how it stands in its next packet
        alvik::buttonPacket(p, 4, true); send(p, 5);
        alvik::buttonPacket(p, 4, false); send(p, 5);
      }
    }
    if (did[i]) dirty = true;
  }
  if (shift != wasShift || tops.waiting()) dirty = true;    // the header changes, and the hold bar grows

  // tilt, for steering and the tilt bar
  float g = TILT_SIGN * lis.TILT_AXIS();
  if (g > 1) g = 1;
  if (g < -1) g = -1;
  tiltDeg = asinf(g) * 57.3f;

  int y = up ? STICK : down ? -STICK : 0;
  int x = right ? STICK : left ? -STICK : 0;
  if (tilt && y) {
    float t = fabsf(tiltDeg) < TILT_DEAD_DEG ? 0 : (tiltDeg - (tiltDeg > 0 ? TILT_DEAD_DEG : -TILT_DEAD_DEG)) / (TILT_FULL_DEG - TILT_DEAD_DEG);
    if (t > 1) t = 1;
    if (t < -1) t = -1;
    if (!x) x = (int)(t * CURVE);
    else x = x > 0 ? CURVE : -CURVE;          // left/right while driving: curve, don't spin
  }
  // send on every change, and again every RESEND_MS while held (the robot stops if it hears nothing)
  bool moving = x || y;
  if (x != sentX || y != sentY || (moving && now - sentAt >= RESEND_MS)) {
    alvik::joystickPacket(p, x, y); send(p, 5);
    if (!moving && (sentX || sentY)) send(p, 5);   // letting go: say so twice
    sentX = x; sentY = y; sentAt = now;
  }
}

// ---------- drawing ----------
static uint16_t ledColour(const uint8_t c[3]) {
  if (!c[0] && !c[1] && !c[2]) return TFT_DARKGREY;
  return tft.color565(c[0] * 255, c[1] * 255, c[2] * 255);
}
static uint16_t heatColour(int cm, bool blocked) {
  if (blocked || cm < BUMPER_CM) return TFT_RED;
  if (cm < (BUMPER_CM + SLOW_CM) / 2) return TFT_ORANGE;
  return TFT_YELLOW;
}

static void drawWaiting() {
  tft.fillScreen(TFT_BLACK);
  tft.setTextDatum(TC_DATUM);
  tft.setTextColor(TFT_YELLOW, TFT_BLACK);
  tft.drawString("Looking for Alvik...", 160, 30, 4);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextDatum(TL_DATUM);
  const char* steps[] = {"1. Robot on, up arrow until PURPLE, then tick", "2. Robot lights go YELLOW = ready",
                         "3. Phone or web remote disconnected", "   (only one remote at a time)"};
  for (int i = 0; i < 4; i++) tft.drawString(steps[i], 12, 90 + i * 26, 2);
}

// first-run diagnostics: each step goes to USB serial and to the bottom of the waiting screen,
// so a freeze shows where it happened even if USB stops answering
static int dbgLine = 0;
static void dbg(const char* fmt, ...) {
  char line[64];
  va_list ap; va_start(ap, fmt); vsnprintf(line, sizeof line, fmt, ap); va_end(ap);
  Serial.printf("[%lu] %s\n", millis(), line);
  if (linkUp) return;
  int y = 180 + (dbgLine % 4) * 15;
  dbgLine++;
  tft.fillRect(0, y, 320, 15, TFT_BLACK);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  char shown[72]; snprintf(shown, sizeof shown, "%d %s", dbgLine, line);
  tft.drawString(shown, 4, y, 2);
}

static void drawRadar() {
  const int cx = RW / 2, cy = RH - 30;       // the robot's nose
  const float px = (cy - 14) / 30.0f;        // pixels per cm: 30 cm reaches the top
  radar.fillSprite(TFT_BLACK);
  // rings where the bumper slows (yellow) and stops (red)
  radar.drawCircle(cx, cy, SLOW_CM * px, 0x52A0);      // dim yellow
  radar.drawCircle(cx, cy, BUMPER_CM * px, 0x8000);    // dim red
  for (int r = 10; r <= 30; r += 10) radar.drawCircle(cx, cy, r * px, 0x2104);
  // the bumper's view: an arc across the middle three zones at the distance it acts on
  const alvik::Telemetry& t = reader.t;
  if (t.distance != alvik::NONE && t.distance < 40) {
    int r = (int)(min(t.distance, 30) * px);
    uint16_t c = t.distance < SLOW_CM || t.blocked ? heatColour(t.distance, t.blocked) : 0x7BEF;
    for (int w = -2; w <= 2; w++)
      for (float a = -16; a <= 16; a += 1.5f) {
        float rad = (90 + a) * 0.01745f;
        radar.drawPixel(cx + (int)(cosf(rad) * (r + w)), cy - (int)(sinf(rad) * (r + w)), c);
      }
  }
  // raw readings: each zone's last three, newest brightest
  const uint16_t fade[3] = {0x8FFF, 0x4C1F, 0x2950};
  for (int z = 0; z < 5; z++)
    for (int k = 2; k >= 0; k--) {
      int cm = zoneHist[z][k];
      if (cm == alvik::NONE || cm > 30) continue;
      float rad = (90 + ZONE_DEG[z]) * 0.01745f;
      radar.fillCircle(cx + (int)(cosf(rad) * cm * px), cy - (int)(sinf(rad) * cm * px), k ? 2 : 4, fade[k]);
    }
  // the robot, seen from above: floor colour under it, LED colours at the front corners
  const alvik::Under& u = reader.u;
  if (u.floor[0] != alvik::NONE)
    radar.fillRoundRect(cx - 34, cy - 4, 68, 34, 6,
                        tft.color565(u.floor[0] * 255 / 100, u.floor[1] * 255 / 100, u.floor[2] * 255 / 100));
  radar.fillRoundRect(cx - 24, cy, 48, 40, 6, 0x4208);
  radar.fillRect(cx - 24, cy + 6, 6, 22, TFT_BLACK);     // wheels
  radar.fillRect(cx + 18, cy + 6, 6, 22, TFT_BLACK);
  radar.fillCircle(cx - 14, cy + 4, 4, ledColour(t.left));   // the robot's left is on our left
  radar.fillCircle(cx + 14, cy + 4, 4, ledColour(t.right));
  for (int i = 0; i < 3; i++) {                         // line sensors at the nose: dark = over a line
    int raw = u.lines[i];
    if (raw == alvik::NONE) continue;
    int shade = raw <= 100 ? 255 : raw >= 500 ? 20 : 255 - (raw - 100) * 235 / 400;
    radar.fillCircle(cx - 8 + i * 8, cy + 12, 3, tft.color565(shade, shade, shade));
  }
  if (t.blocked) {
    radar.setTextDatum(TC_DATUM);
    radar.setTextColor(TFT_RED);
    radar.drawString("STOP!", cx, 4, 4);
  }
  radar.pushSprite(0, 26);
}

static void drawPanel() {
  const alvik::Telemetry& t = reader.t;
  const alvik::Sensors& s = reader.s;
  panel.fillSprite(TFT_BLACK);
  panel.setTextDatum(TL_DATUM);
  // battery
  int b = s.battery;
  panel.drawRect(4, 4, 100, 16, TFT_WHITE);
  panel.fillRect(104, 9, 4, 6, TFT_WHITE);
  if (b != alvik::NONE) panel.fillRect(6, 6, b * 96 / 100, 12, b > 30 ? TFT_GREEN : b > 15 ? TFT_YELLOW : TFT_RED);
  // speed and distance
  char line[24];
  panel.setTextColor(TFT_WHITE);
  snprintf(line, sizeof line, "%d cm/s", (int)roundf(fabsf(t.speed)));
  panel.drawString(line, 4, 28, 4);
  panel.setTextColor(TFT_LIGHTGREY);
  if (t.distance != alvik::NONE) snprintf(line, sizeof line, "wall %d cm", t.distance);
  else snprintf(line, sizeof line, "nothing ahead");
  panel.drawString(line, 4, 58, 2);
  // compass: which way the robot points (from its wheels)
  const int ox = 60, oy = 112, r = 26;
  panel.drawCircle(ox, oy, r, TFT_DARKGREY);
  float h = t.heading * 0.01745f;
  panel.drawLine(ox, oy, ox - (int)(sinf(h) * r), oy - (int)(cosf(h) * r), TFT_CYAN);
  panel.fillCircle(ox - (int)(sinf(h) * r), oy - (int)(cosf(h) * r), 3, TFT_CYAN);
  // flags
  panel.setTextColor(t.turbo ? TFT_ORANGE : TFT_DARKGREY);
  panel.drawString("TURBO", 4, 146, 2);
  panel.setTextColor(t.bumper ? TFT_GREEN : TFT_RED);
  panel.drawString(t.bumper ? "BUMPER" : "NO BUMP", 58, 146, 2);
  // tilt steering
  panel.setTextColor(tilt ? TFT_CYAN : TFT_DARKGREY);
  panel.drawString(tilt ? "TILT: on" : "TILT: off", 4, 168, 2);
  int bar = (int)(tiltDeg / TILT_FULL_DEG * 50);
  bar = bar > 50 ? 50 : bar < -50 ? -50 : bar;
  panel.drawFastHLine(10, 196, 100, TFT_DARKGREY);
  panel.fillRect(bar >= 0 ? 60 : 60 + bar, 192, abs(bar) + 1, 9, tilt ? TFT_CYAN : TFT_DARKGREY);
  panel.pushSprite(RW, 26);
}

// The top strip names the three buttons above it. With the stick pressed in it turns purple and names
// the grown-up switches instead, with a bar that fills while one is held.
static void drawHeader() {
  const uint16_t bg = shift ? 0x4010 : 0x18E3;         // purple : dark grey
  uint32_t now = millis();
  tft.fillRect(0, 0, 320, 24, bg);
  tft.setTextDatum(MC_DATUM);
  for (int i = 0; i < 3; i++) {
    tft.setTextColor(tops.isDown(i) ? TFT_YELLOW : TFT_WHITE, bg);
    tft.drawString(shift ? TOP_SWITCH_LABEL[i] : TOP_LABEL[i], 34 + i * 70, 10, 2);
    float held = tops.progress(i, now);
    if (held >= 0) tft.fillRect(4 + i * 70, 20, (int)(60 * held), 4, TFT_YELLOW);
  }
  tft.setTextColor(shift ? TFT_WHITE : TFT_GREEN, bg);
  tft.drawString(shift ? "hold" : "Alvik", 286, 10, 2);
}

// ---------- main ----------
void setup() {
  Serial.begin(115200);
  for (int pin : {WIO_5S_UP, WIO_5S_DOWN, WIO_5S_LEFT, WIO_5S_RIGHT, WIO_5S_PRESS, WIO_KEY_A, WIO_KEY_B, WIO_KEY_C})
    pinMode(pin, INPUT_PULLUP);
  for (auto& z : zoneHist) for (int& v : z) v = alvik::NONE;
  for (int i = 0; i < 3; i++) tops.grownUp[i] = TOP_SWITCH[i] != NO_SWITCH;
  tft.begin();
  tft.setRotation(3);                        // landscape, buttons along the top
  radar.setColorDepth(8);
  radar.createSprite(RW, RH);
  panel.setColorDepth(8);
  panel.createSprite(PW, RH);
  lis.begin(Wire1);
  lis.setOutputDataRate(LIS3DHTR_DATARATE_50HZ);
  lis.setFullScaleRange(LIS3DHTR_RANGE_2G);
  drawWaiting();
  waitingShown = true;
  while (!Serial && millis() < 8000) delay(10);   // give a serial monitor a moment to attach
  dbg("before Bluetooth start");
  BLEDevice::init("");
  dbg("Bluetooth started");
  dbg("wireless firmware: %s", rpc_system_version());
}

void loop() {
  if (!linkUp) {
    rx = nullptr;
    if (!waitingShown) { drawWaiting(); waitingShown = true; }
    if (findRobot() && hookUp()) {
      failures = 0;
      waitingShown = false;
      tft.fillScreen(TFT_BLACK);
      drawHeader();
      dirty = true;
    } else if (robotAddr && ++failures >= 5) {
      NVIC_SystemReset();                    // Bluetooth got itself stuck: start over (takes a second)
    }
    return;
  }

  // what the robot told us
  uint8_t chunk[64];
  size_t n = 0;
  while (ringTail != ringHead && n < sizeof chunk) { chunk[n++] = ring[ringTail]; ringTail = (ringTail + 1) & 255; }
  if (n) {
    int got = reader.feed(chunk, n);
    uint32_t now = millis();
    if (got & alvik::Reader::GOT_T) { lastT = now; startBumper(now); }
    if (got & alvik::Reader::GOT_U) lastU = now;
    if (got & alvik::Reader::GOT_S) {
      lastS = now;
      for (int z = 0; z < 5; z++) { zoneHist[z][2] = zoneHist[z][1]; zoneHist[z][1] = zoneHist[z][0]; zoneHist[z][0] = reader.s.zones[z]; }
    }
    if (got) dirty = true;
  }
  // no telemetry yet (or it stopped): ask again
  if (millis() - lastT > 1500 && millis() - askedAt > 1500) {
    uint8_t p[5];
    alvik::telemetryRequest(p, true); send(p, 5);
    askedAt = millis();
  }

  readInput();

  if (dirty && millis() - drawnAt >= DRAW_MS) {
    drawnAt = millis();
    dirty = false;
    drawHeader();
    drawRadar();
    drawPanel();
  }
  delay(5);
}
