//#define SERIAL_DEBUG

#define LGFX_USE_V1      // set to use new version of library
#include <LovyanGFX.hpp> // main library
#include "lv_conf.h"
#include <lvgl.h>

class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ST7796 _panel_instance;
  lgfx::Bus_SPI _bus_instance;       // SPI cho màn hình
  lgfx::Touch_XPT2046 _touch_instance;

public:
  LGFX(void) {
    { // Cấu hình SPI Bus cho LCD
      auto cfg = _bus_instance.config();
      cfg.spi_host =
          HSPI_HOST;    // Sử dụng HSPI cho các chân 12, 13, 14, 15 (native)
      cfg.spi_mode = 0; // SPI mode
      cfg.freq_write = 20000000; // Hạ xuống 20MHz để ổn định
      cfg.freq_read = 16000000;  // Tần số đọc
      cfg.pin_sclk = 14;         // Chân SCK
      cfg.pin_mosi = 13;         // Chân MOSI
      cfg.pin_miso = 12;         // Chân MISO
      cfg.pin_dc = 2;            // Chân DC
      _bus_instance.config(cfg);
      _panel_instance.setBus(&_bus_instance);
    }

    { // Cấu hình Panel
      auto cfg = _panel_instance.config();
      cfg.pin_cs = 15;  // Chân CS
      cfg.pin_rst = 22; // Chân RST
      cfg.pin_busy = -1;
      cfg.panel_width = 320;  // Độ rộng thực tế
      cfg.panel_height = 480; // Độ cao thực tế
      cfg.offset_x = 0;
      cfg.offset_y = 0;
      cfg.offset_rotation = 0;
      cfg.dummy_read_pixel = 8;
      cfg.dummy_read_bits = 1;
      cfg.readable = true;
      cfg.invert = false;
      cfg.rgb_order = false;
      cfg.dlen_16bit = false;
      cfg.bus_shared = true; // Dùng chung SPI với SD Card (theo hình)
      _panel_instance.config(cfg);
    }

    { // Cấu hình Touch
      auto cfg = _touch_instance.config();
      // Các giá trị này được tính toán từ dữ liệu thực tế bạn cung cấp
      cfg.x_min = 3800; // Giá trị Raw tại X=0 (bên trái)
      cfg.x_max = 200;  // Giá trị Raw tại X=480 (bên phải)
      cfg.y_min = 800;  // Giá trị Raw tại Y=0 (phía trên) - tương ứng ~64500
      cfg.y_max = 3800; // Giá trị Raw tại Y=320 (phía dưới)
      cfg.pin_int = 36; // T_IRQ
      cfg.bus_shared = true;
      cfg.offset_rotation = 0;

      // Cấu hình SPI cho Touch (dùng chung bus HSPI của LCD)
      cfg.spi_host = HSPI_HOST;
      cfg.freq = 1000000; // Thử tần số thấp 1MHz cho an toàn
      cfg.pin_sclk = 14;  // Dùng chung chân SCK của màn hình
      cfg.pin_mosi = 13;  // Dùng chung chân MOSI của màn hình
      cfg.pin_miso = 12;  // Dùng chung chân MISO của màn hình
      cfg.pin_cs = 33;    // T_CS vẫn là 33 (theo hình)

      _touch_instance.config(cfg);
      _panel_instance.setTouch(&_touch_instance);
    }

    _panel_instance.setRotation(1); // Cố định hướng Landscape

    setPanel(&_panel_instance);
  }
};

static LGFX lcd; // declare display variable

static const uint16_t screenWidth = 480;
static const uint16_t screenHeight = 320;
static lv_disp_draw_buf_t draw_buf;
static lv_color_t buf[screenWidth * 10];

#define PREPROC_NOISE_THRESHOLD 200
#define CANVAS_BIG_SIZE 280
#define CANVAS_MNIST_SIZE 28
#define INNER_GRID_SIZE 20
#define PADDING 4

#define AUTO_TRIGGER_DELAY_MS 600
static lv_timer_t *auto_trigger_timer = NULL;
static bool is_drawing = false;

static lv_obj_t *canvas_big;
static uint8_t *canvas_big_buf;
static lv_point_t last_p = {-1, -1}; // Đưa ra toàn cục để CLEAR có thể reset

/*** Function declaration ***/
void display_flush(lv_disp_drv_t *disp, const lv_area_t *area,
                  lv_color_t *color_p);
void touchpad_read(lv_indev_drv_t *indev_driver, lv_indev_data_t *data);
static void send_drawing(void);
static void clear_drawing(void);
static void auto_trigger_timer_cb(lv_timer_t *timer);
static void select_event_handler(lv_event_t *e);
static void start_event_handler(lv_event_t *e);
static void draw_event_handler(lv_event_t *e);
void create_mnist_ui(void);




void display_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p) {
  uint32_t w = (area->x2 - area->x1 + 1);
  uint32_t h = (area->y2 - area->y1 + 1);

  lcd.startWrite();
  lcd.setAddrWindow(area->x1, area->y1, w, h);
  lcd.pushPixels((uint16_t *)&color_p->full, w * h, true);
  lcd.endWrite();

  lv_disp_flush_ready(disp);
}

void touchpad_read(lv_indev_drv_t *indev_driver, lv_indev_data_t *data) {
  uint16_t touchX, touchY;
  bool touched = lcd.getTouch(&touchX, &touchY);

  if (!touched) {
    data->state = LV_INDEV_STATE_REL;
  } else {
    data->state = LV_INDEV_STATE_PR;
    
    /*Set the coordinates*/
    data->point.x = touchX;
    data->point.y = touchY;

    #ifdef SERIAL_DEBUG
    Serial.printf("Mapped Touch: (%d, %d)\n", touchX, touchY);
    #endif
  }
}

static void send_drawing(void) {

  //20x20 average pooling on 28x28 canvas
  uint8_t mnist_data[CANVAS_MNIST_SIZE * CANVAS_MNIST_SIZE];
  memset(mnist_data, 0, 28 * 28);

  int scale = CANVAS_BIG_SIZE / INNER_GRID_SIZE;

  for (int my = 0; my < INNER_GRID_SIZE; my++) {
  for (int mx = 0; mx < INNER_GRID_SIZE; mx++) {
            
    uint32_t sum = 0;
    for (int dy = 0; dy < scale; dy++) {
      for (int dx = 0; dx < scale; dx++) {
        sum += canvas_big_buf[(my * scale + dy) * CANVAS_BIG_SIZE + (mx * scale + dx)];
      }
    }

    uint8_t avg_pixel = (uint8_t)(sum / (scale * scale));
    int target_x = mx + PADDING;
    int target_y = my + PADDING;

    int target_index = (CANVAS_MNIST_SIZE - 1- target_x) * CANVAS_MNIST_SIZE + target_y; 
            
    if(avg_pixel > 150 && avg_pixel < PREPROC_NOISE_THRESHOLD)
      avg_pixel += 50;
    else if(avg_pixel > 100 && avg_pixel < 150)
      avg_pixel += 30;
    else if(avg_pixel > 0 && avg_pixel < 100)
      avg_pixel = 0;

    mnist_data[target_index] = avg_pixel;
  }
  }


  
  Serial.print("[DATA] ");
  for (int i = 0; i < 784; i++) {
    if (mnist_data[i] < 16) Serial.print("0"); // Pad single-digit hex values
      Serial.print(mnist_data[i], HEX);
  }
  Serial.println(); // Ends with \n

  #ifdef SERIAL_DEBUG
  Serial.println(">>> Data Sent to PC and Simulated on Console!");
  #endif
}

static void clear_drawing(void) {
  lv_canvas_fill_bg(canvas_big, lv_color_make(0, 0, 0), 0);

  // QUAN TRỌNG: Reset tọa độ vẽ để không bị kéo nét từ hình cũ sang hình mới
  last_p.x = -1;
  last_p.y = -1;

  lv_obj_invalidate(canvas_big);

  #ifdef SERIAL_DEBUG
  Serial.println("Canvas Cleared!");
  #endif
}

static void auto_trigger_timer_cb(lv_timer_t *timer) {

  #ifdef SERIAL_DEBUG
  Serial.println("Auto-trigger fired.");
  #endif

  send_drawing();
  clear_drawing();

  // Delete the timer after firing (one-shot behavior)
  if (auto_trigger_timer != NULL) {
    lv_timer_del(auto_trigger_timer);
    auto_trigger_timer = NULL;
  }
}

static void select_event_handler(lv_event_t *e) {
  if (is_drawing) return; // Ignore click if user is drawing
  
  lv_event_code_t code = lv_event_get_code(e);
  if (code == LV_EVENT_CLICKED) {
    Serial.println("[CMD] SELECT");
    Serial.flush();
  }
}

static void start_event_handler(lv_event_t *e) {
  if (is_drawing) return; // Ignore click if user is drawing
  
  lv_event_code_t code = lv_event_get_code(e);
  if (code == LV_EVENT_CLICKED) {
    Serial.println("[CMD] START");
    Serial.flush();
  }
}

static void draw_event_handler(lv_event_t *e) {
  lv_event_code_t code = lv_event_get_code(e);
  lv_obj_t *obj = lv_event_get_target(e);

  if (code == LV_EVENT_PRESSED) {
    is_drawing = true; // User started drawing
    
    // Stop the auto-trigger timer if the user touches the canvas again
    if (auto_trigger_timer != NULL) {
      lv_timer_del(auto_trigger_timer);
      auto_trigger_timer = NULL;

      #ifdef SERIAL_DEBUG
      Serial.println("Auto-trigger timer cancelled (user drawing...)");
      #endif
    }

    // Bắt đầu nét mới: lấy tọa độ chạm đầu tiên
    lv_indev_t *indev = lv_indev_get_act();
    lv_point_t curr_p;
    lv_indev_get_point(indev, &curr_p);
    last_p.x = curr_p.x - obj->coords.x1;
    last_p.y = curr_p.y - obj->coords.y1;

  } else if (code == LV_EVENT_PRESSING) {
    is_drawing = true;
    
    lv_indev_t *indev = lv_indev_get_act();
    lv_point_t curr_p;
    lv_indev_get_point(indev, &curr_p);

    lv_point_t p_canvas;
    p_canvas.x = curr_p.x - obj->coords.x1;
    p_canvas.y = curr_p.y - obj->coords.y1;

    if (p_canvas.x >= 0 && p_canvas.x < CANVAS_BIG_SIZE && p_canvas.y >= 0 &&
        p_canvas.y < CANVAS_BIG_SIZE && last_p.x >= 0) {

      // Nội suy đường thẳng giữa 2 điểm liên tiếp
      lv_draw_line_dsc_t line_dsc;
      lv_draw_line_dsc_init(&line_dsc);
      line_dsc.color = lv_color_white();
      line_dsc.width = 30;
      line_dsc.round_start = true;
      line_dsc.round_end = true;

      lv_point_t points[2] = {last_p, p_canvas};
      lv_canvas_draw_line(canvas_big, points, 2, &line_dsc);

      last_p = p_canvas;
      lv_obj_invalidate(canvas_big);
    }

  } else if (code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) {
    is_drawing = false; // User stopped drawing (released or touch lost/dragged out)
    
    // Nhấc tay: reset để nét tiếp theo không nối vào nét cũ
    last_p.x = -1;
    last_p.y = -1;

    // Start/reset the auto-trigger timer when user lifts finger
    if (auto_trigger_timer != NULL) {
      lv_timer_del(auto_trigger_timer);
    }
    auto_trigger_timer = lv_timer_create(auto_trigger_timer_cb, AUTO_TRIGGER_DELAY_MS, NULL);

    #ifdef SERIAL_DEBUG
    Serial.println("Auto-trigger timer started (0.6s)");
    #endif
  }
}

void create_mnist_ui(void) {
  // Background chung cho màn hình
  lv_obj_set_style_bg_color(lv_scr_act(), lv_color_make(122, 121, 121), 0);

  // 1. Canvas Vẽ lớn (224x224) - ALPHA_8BIT 
  canvas_big = lv_canvas_create(lv_scr_act());
  int canvas_big_alloc = CANVAS_BIG_SIZE * CANVAS_BIG_SIZE;
  canvas_big_buf = (uint8_t *)malloc(canvas_big_alloc);
  if (canvas_big_buf == NULL) {

    #ifdef SERIAL_DEBUG
    Serial.println(">>> FATAL ERROR: OUT OF RAM!");
    #endif

    return;
  }

  #ifdef SERIAL_DEBUG
  Serial.printf("Canvas Big: %d bytes allocated (8-bit)\n", canvas_big_alloc);
  #endif

  lv_canvas_set_buffer(canvas_big, canvas_big_buf, CANVAS_BIG_SIZE,
                      CANVAS_BIG_SIZE, LV_IMG_CF_ALPHA_8BIT);
  lv_obj_align(canvas_big, LV_ALIGN_RIGHT_MID, -10, 0);

  // Hiển thị nét vẽ trắng trên nền đen bằng kỹ thuật recolor
  lv_obj_set_style_img_recolor(canvas_big, lv_color_white(), 0);
  lv_obj_set_style_img_recolor_opa(canvas_big, 255, 0);
  lv_obj_set_style_bg_color(canvas_big, lv_color_make(94,120,93), 0);
  lv_obj_set_style_bg_opa(canvas_big, 255, 0);

  // Nền trong suốt (sẽ hiển thị màu nền của widget canvas)
  lv_canvas_fill_bg(canvas_big, lv_color_make(0, 0, 0), 0);

  // Đăng ký cả 3 sự kiện: PRESSED, PRESSING, RELEASED
  // để xử lý đúng nội suy (nhấc tay = kết thúc nét, không nối nét cũ)
  lv_obj_add_event_cb(canvas_big, draw_event_handler, LV_EVENT_PRESSED, NULL);
  lv_obj_add_event_cb(canvas_big, draw_event_handler, LV_EVENT_PRESSING, NULL);
  lv_obj_add_event_cb(canvas_big, draw_event_handler, LV_EVENT_RELEASED, NULL);
  lv_obj_add_flag(canvas_big, LV_OBJ_FLAG_CLICKABLE);

  // Khung viền cho Canvas lớn
  lv_obj_set_style_outline_color(canvas_big, lv_color_make(85,90,86), 0);
  lv_obj_set_style_outline_width(canvas_big, 5, 0);

  // 2. Nút bấm
  lv_obj_t *btn_send = lv_btn_create(lv_scr_act());
  lv_obj_set_size(btn_send, 55, 130);
  lv_obj_align(btn_send, LV_ALIGN_TOP_LEFT, 55, 15);
  lv_obj_set_style_bg_color(btn_send, lv_color_make(154, 34, 87), 0);
  lv_obj_add_event_cb(btn_send, select_event_handler, LV_EVENT_CLICKED, NULL);
  lv_obj_t *label_send = lv_label_create(btn_send);
  lv_label_set_text(label_send, "O");
  lv_obj_set_style_text_font(label_send, &lv_font_montserrat_32, 0);
  lv_obj_center(label_send);

  lv_obj_t *btn_clear = lv_btn_create(lv_scr_act());
  lv_obj_set_size(btn_clear, 55, 130);
  lv_obj_align(btn_clear, LV_ALIGN_TOP_LEFT, 55, 175);
  lv_obj_set_style_bg_color(btn_clear, lv_color_make(154, 34, 87), 0);
  lv_obj_add_event_cb(btn_clear, start_event_handler, LV_EVENT_CLICKED, NULL);
  lv_obj_t *label_clear = lv_label_create(btn_clear);
  lv_label_set_text(label_clear, "X");
  lv_obj_set_style_text_font(label_clear, &lv_font_montserrat_32, 0);
  lv_obj_center(label_clear);
}

void setup(void) {
  Serial.begin(115200); /* prepare for possible serial debug */
  delay(1000);

  // Khởi tạo UART2 sang Sonix
  #ifdef SERIAL_DEBUG
  Serial.println("UART2 Initialized (RX=35, TX=21)");
  #endif

  #ifdef SERIAL_DEBUG
  Serial.print("Initializing LGFX... ");
  #endif
  if (lcd.init()) {
    #ifdef SERIAL_DEBUG
    Serial.println("SUCCESS");
    #endif
  } else {
    #ifdef SERIAL_DEBUG
    Serial.println("FAIL");
    #endif
  }

  #ifdef SERIAL_DEBUG
  Serial.println("LCD width x height: " + String(lcd.width()) + " x " +
                String(lcd.height()));
  #endif

  // Setup backlight - Cố định ở chân 27 (đã chẩn đoán thành công)
  pinMode(27, OUTPUT);
  digitalWrite(27, HIGH);
  delay(500);

  // Test: Draw solid color to verify LCD works
  #ifdef SERIAL_DEBUG
  Serial.println("Testing LCD with RED color...");
  lcd.fillScreen(TFT_RED);
  #endif

  delay(500);
  lcd.fillScreen(TFT_BLACK);

  // ÁP DỤNG DỮ LIỆU HIỆU CHUẨN ĐÃ THU THẬP (PHỤC HỒI)
  uint16_t calData[] = {3865, 3870, 3874, 239, 343, 3850, 259, 246};
  lcd.setTouchCalibrate(calData);
  #ifdef SERIAL_DEBUG
  Serial.println("Touch Calibration Restored.");
  #endif

  #ifdef SERIAL_DEBUG
  Serial.println("Initializing LVGL...");
  #endif
  lv_init(); // Initialize lvgl

  // Setting display to landscape
  lcd.setRotation(1);

  /* LVGL : Setting up buffer to use for display */
  lv_disp_draw_buf_init(&draw_buf, buf, NULL, screenWidth * 10);

  /*** LVGL : Setup & Initialize the display device driver ***/
  static lv_disp_drv_t disp_drv;
  lv_disp_drv_init(&disp_drv);
  disp_drv.hor_res = screenWidth;
  disp_drv.ver_res = screenHeight;
  disp_drv.flush_cb = display_flush;
  disp_drv.draw_buf = &draw_buf;
  lv_disp_drv_register(&disp_drv);

  /*** LVGL : Setup & Initialize the input device driver ***/
  static lv_indev_drv_t indev_drv;
  lv_indev_drv_init(&indev_drv);
  indev_drv.type = LV_INDEV_TYPE_POINTER;
  indev_drv.read_cb = touchpad_read;
  lv_indev_drv_register(&indev_drv);

  // GIAO DIỆN MNIST
  create_mnist_ui();

  #ifdef SERIAL_DEBUG
  Serial.println("Setup complete!");
  #endif
}

void loop() {
  lv_timer_handler(); /* let the GUI do its work */
  delay(5);

#ifdef DRAW_ON_SCREEN
  /*** Draw on screen with touch ***/
  uint16_t x, y;
  if (lcd.getTouch(&x, &y)) {
    lcd.fillRect(x - 2, y - 2, 5, 5, TFT_RED);
    lcd.setCursor(380, 0);
    lcd.printf("Touch:(%03d,%03d)", x, y);
  }
#endif
}
