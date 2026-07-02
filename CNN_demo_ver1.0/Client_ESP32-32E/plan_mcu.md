# 📋 Kế hoạch tích hợp hệ thống MNIST Digit Recognition

## Thành viên nhóm cần đọc trước khi họp

---

## 1. Tổng quan hệ thống

```
┌─────────────────┐     UART 115200     ┌─────────────────┐     SPI / GPIO     ┌─────────────────┐
│                 │    TX=21, RX=35     │                 │                    │                 │
│     ESP32       │ ──────────────────► │   SONIX MCU     │ ─────────────────► │     FPGA        │
│   (Giao diện)   │    784 bytes        │  (Điều khiển)   │    784 bytes       │   (AI Core)     │
│                 │ ◄────────────────── │                 │ ◄───────────────── │                 │
│  LCD 3.5" Touch │   Kết quả (0-9)    │                 │   10 scores        │  Neural Network │
└─────────────────┘                    └─────────────────┘                    └─────────────────┘
```

### Vai trò từng thành phần

| Thành phần | Vai trò chính | Công nghệ / Ngôn ngữ |
|---|---|---|
| **ESP32** | Giao diện người dùng (HMI): Vẽ số, hiển thị kết quả | C++ / Arduino / LVGL 8.3 |
| **Sonix MCU** | Bộ điều phối: Tiền xử lý dữ liệu, giao tiếp 2 chiều | C / Sonix SDK |
| **FPGA** | Bộ tăng tốc AI: Chạy mạng neural phần cứng | Verilog / VHDL |

---

## 2. Giao thức truyền thông

### 2.1. ESP32 → Sonix MCU (UART)

**Gói tin gửi ảnh (788 bytes):**
```
Byte 0     : 0xAA  (Header 1)
Byte 1     : 0xBB  (Header 2)
Byte 2~785 : 784 bytes pixel data (28×28, row-major, grayscale 0-255)
Byte 786   : 0xCC  (Footer 1)
Byte 787   : 0xDD  (Footer 2)
```

**Ý nghĩa giá trị pixel:**
- `0x00` (0)   = Nền đen (không vẽ)
- `0xFF` (255) = Nét trắng đậm nhất
- Thứ tự: Từ trái → phải, trên → dưới (giống chuẩn MNIST)

### 2.2. Sonix MCU → ESP32 (UART)

**Gói tin trả kết quả (5 bytes):**
```
Byte 0 : 0xDD  (Header 1)
Byte 1 : 0xEE  (Header 2)
Byte 2 : Predicted digit (0x00 ~ 0x09)
Byte 3 : Confidence % (0x00 ~ 0x64, tức 0~100%)
Byte 4 : 0xFF  (Footer)
```

### 2.3. Sonix MCU ↔ FPGA (SPI hoặc GPIO bus)

**Sonix → FPGA:**
- 784 bytes dữ liệu đã chuẩn hóa (fixed-point)
- 1 tín hiệu START (GPIO) để kích hoạt suy luận

**FPGA → Sonix:**
- 10 giá trị scores (mỗi giá trị 16-bit, tổng 20 bytes)
- 1 tín hiệu DONE (GPIO) báo xử lý xong

---

## 3. Nhiệm vụ chi tiết từng thành phần

### 3.1. ESP32 (✅ ĐÃ HOÀN THÀNH)

- [x] Giao diện vẽ MNIST (LVGL Canvas 250×250)
- [x] Nội suy nét vẽ (Bresenham line)
- [x] Thu nhỏ 250×250 → 28×28 (ánh xạ tọa độ)
- [x] Truyền 784 bytes qua UART2
- [x] LED trạng thái (GPIO 4)
- [ ] **TODO**: Nhận kết quả từ Sonix và hiển thị lên màn hình

### 3.2. Sonix MCU (⏳ CẦN LÀM)

#### Tiền xử lý (Preprocessing):

- [ ] **Nhận gói tin UART** từ ESP32
  - Đợi header `0xAA 0xBB`
  - Nhận 784 bytes vào buffer
  - Kiểm tra footer `0xCC 0xDD`
  - Nếu sai → bỏ gói, gửi NACK

- [ ] **Chuẩn hóa dữ liệu (Normalization)**
  ```c
  // Chuyển 0-255 sang fixed-point Q1.7 (0.0 ~ 1.0)
  for(int i = 0; i < 784; i++) {
      fixed_point[i] = (uint8_t)((raw[i] * 128) / 255);
  }
  ```

- [ ] **Căn giữa hình ảnh (Center of Mass) ⭐ QUAN TRỌNG**
  ```c
  // Bước 1: Tính trọng tâm
  float cx = 0, cy = 0, total = 0;
  for(int y = 0; y < 28; y++) {
      for(int x = 0; x < 28; x++) {
          uint8_t val = buf[y * 28 + x];
          cx += x * val;
          cy += y * val;
          total += val;
      }
  }
  cx /= total;  // Trọng tâm X
  cy /= total;  // Trọng tâm Y
  
  // Bước 2: Dịch chuyển để trọng tâm nằm ở (14, 14)
  int dx = 14 - (int)cx;
  int dy = 14 - (int)cy;
  // Dịch toàn bộ pixel theo (dx, dy)
  ```
  > **Tại sao cần căn giữa?**
  > Dataset MNIST gốc được huấn luyện với chữ số nằm giữa khung 28×28.
  > Nếu người dùng viết lệch góc, model sẽ nhận sai.
  > Bước này giúp tăng độ chính xác đáng kể (~5-10%).

- [ ] **Gửi dữ liệu sang FPGA** qua SPI
  ```c
  SPI_CS_LOW();
  SPI_SendBuffer(normalized, 784);
  SPI_CS_HIGH();
  GPIO_Write(FPGA_START, HIGH);  // Kích hoạt suy luận
  ```

#### Hậu xử lý (Postprocessing):

- [ ] **Nhận kết quả từ FPGA**
  ```c
  while(GPIO_Read(FPGA_DONE) == LOW);  // Đợi FPGA xong
  int16_t scores[10];
  SPI_ReadBuffer(scores, 20);  // 10 × 2 bytes
  ```

- [ ] **Argmax — Chọn kết quả**
  ```c
  uint8_t predicted = 0;
  int16_t max_score = scores[0];
  for(int i = 1; i < 10; i++) {
      if(scores[i] > max_score) {
          max_score = scores[i];
          predicted = i;
      }
  }
  ```

- [ ] **Tính Confidence (%)**
  ```c
  int32_t sum = 0;
  for(int i = 0; i < 10; i++) sum += scores[i];
  uint8_t confidence = (uint8_t)((max_score * 100) / sum);
  ```

- [ ] **Gửi kết quả về ESP32**
  ```c
  UART_Send(0xDD);
  UART_Send(0xEE);
  UART_Send(predicted);    // Chữ số 0-9
  UART_Send(confidence);   // Độ tin cậy 0-100%
  UART_Send(0xFF);
  ```

### 3.3. FPGA (⏳ CẦN LÀM)

- [ ] **Thiết kế kiến trúc mạng neural**
  - Gợi ý: MLP (Multi-Layer Perceptron)
  - Cấu trúc: `784 → 128 → 64 → 10`
  - Activation: ReLU (đơn giản cho FPGA)
  - Output: 10 giá trị raw (Sonix sẽ tính argmax)

- [ ] **Module nhận dữ liệu SPI**
  - Nhận 784 bytes từ Sonix
  - Lưu vào Block RAM

- [ ] **Module tính toán MAC (Multiply-Accumulate)**
  - Song song hóa phép nhân ma trận
  - Sử dụng DSP blocks trên FPGA

- [ ] **Module trả kết quả**
  - Xuất 10 scores qua SPI
  - Kích hoạt tín hiệu DONE

- [ ] **Huấn luyện model trên PC**
  - Dùng Python/TensorFlow huấn luyện MLP trên MNIST dataset
  - Export trọng số (weights) sang dạng fixed-point
  - Nạp trọng số vào ROM/Block RAM của FPGA

---

## 4. Kết nối phần cứng (Pinout)

### ESP32 ↔ Sonix MCU
```
ESP32 GPIO 21 (TX) ──── Sonix RX
ESP32 GPIO 35 (RX) ──── Sonix TX
ESP32 GND          ──── Sonix GND
```

### Sonix MCU ↔ FPGA (Đề xuất SPI)
```
Sonix MOSI  ──── FPGA SPI_DIN
Sonix MISO  ──── FPGA SPI_DOUT
Sonix SCK   ──── FPGA SPI_CLK
Sonix CS    ──── FPGA SPI_CS
Sonix GPIOx ──── FPGA START (input)
FPGA GPIOx  ──── Sonix DONE (input)
Sonix GND   ──── FPGA GND
```

### LED trạng thái
```
ESP32 GPIO 4  ──── LED (qua trở 220Ω) ──── GND
ESP32 GPIO 27 ──── LCD Backlight
```

---

## 5. Timeline đề xuất

| Tuần | Công việc | Phụ trách |
|---|---|---|
| Tuần 1 | ESP32 hoàn thiện (nhận + hiển thị kết quả) | Người 1 |
| Tuần 1 | Sonix: Nhận UART + chuẩn hóa + căn giữa | Người 2 |
| Tuần 1-2 | FPGA: Thiết kế MLP module | Người 3 |
| Tuần 2 | Huấn luyện model trên PC, export weights | Cả nhóm |
| Tuần 2 | Sonix ↔ FPGA: Tích hợp SPI | Người 2+3 |
| Tuần 3 | Tích hợp toàn hệ thống + Debug | Cả nhóm |
| Tuần 3 | Demo + Báo cáo | Cả nhóm |

---

## 6. Câu hỏi cần thảo luận trong nhóm

1. **Sonix MCU** dùng dòng nào? Có SPI hardware không?
2. **FPGA** dùng board nào? Bao nhiêu DSP blocks? Bao nhiêu Block RAM?
3. **Fixed-point format**: Dùng Q8.8 (16-bit) hay Q1.7 (8-bit)?
4. **Giao tiếp Sonix ↔ FPGA**: SPI hay bus song song (8-bit parallel)?
5. **Thời gian suy luận mục tiêu**: Dưới 100ms? 50ms?
6. **Model size**: MLP 784→128→10 hay cần lớn hơn?

---

## 7. Tham khảo

- [MNIST Dataset](http://yann.lecun.com/exdb/mnist/) - 60,000 ảnh train, 10,000 ảnh test
- Độ chính xác MLP trên MNIST: ~97-98%
- Độ chính xác CNN trên MNIST: ~99%+
- Fixed-point Neural Network: [Quantization Guide](https://arxiv.org/abs/1712.05877)

---

*Tài liệu này được tạo ngày 13/04/2026. Cập nhật lần cuối bởi hệ thống AI.*
*Mọi thay đổi cần được cả nhóm đồng ý trước khi triển khai.*
