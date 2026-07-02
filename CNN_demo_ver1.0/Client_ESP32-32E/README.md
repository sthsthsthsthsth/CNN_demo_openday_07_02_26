# ESP32 3.5" TFT LVGL Project (Cheap Chinese Board Variant)

Dự án này được tối ưu hóa cho dòng board ESP32 tích hợp màn hình 3.5 inch giá rẻ của Trung Quốc (thường có chân cắm khác với WT32-SC01 chính gốc).

## 🛠 Thông số kỹ thuật (Hardware Specs)

- **MCU**: ESP32 (Không có PSRAM).
- **Màn hình (TFT)**: 3.5 inch, độ phân giải 320x480 (Thử nghiệm thành công với driver **ST7796**).
- **Cảm ứng (Touch)**: Cảm ứng điện trở chip **XPT2046** (Dùng chung bus SPI với màn hình).
- **Đèn nền (Backlight)**: Chân **27** (Active HIGH).

## 📌 Sơ đồ chân (Pinout)

### 1. Màn hình & Thẻ nhớ (SPI - HSPI Host)
| Chức năng | Chân GPIO | Ghi chú |
| :--- | :--- | :--- |
| **SCK** | 14 | Dùng chung LCD & Touch & SD |
| **MOSI** | 13 | Dùng chung LCD & Touch & SD |
| **MISO** | 12 | Dùng chung LCD & Touch & SD |
| **LCD CS** | 15 | |
| **LCD DC/RS** | 2 | |
| **LCD RST** | 22 | |
| **SD CS** | 5 | |

### 2. Cảm ứng (Touch XPT2046)
| Chức năng | Chân GPIO | Ghi chú |
| :--- | :--- | :--- |
| **T_CS** | 33 | Chip Select cho Touch |
| **T_IRQ** | 36 | Ngắt cảm ứng (Input Only) |
| **SPI Host** | HSPI | Chạy chung bus 14/13/12 |

### 3. Ngoại vi khác
| Chức năng | Chân GPIO | Ghi chú |
| :--- | :--- | :--- |
| **Backlight** | **27** | Kích mức HIGH để bật |
| **LED Đỏ** | 4 | |
| **LED Xanh lá** | 16 | |
| **LED Xanh dương**| 17 | |
| **Audio** | 26 | Loa/Buzzer |
| **LDR** | 34 | Cảm biến ánh sáng (Analog) |

## 📐 Hiệu chuẩn cảm ứng (Touch Calibration)

Để cảm ứng hoạt động chính xác trên board này, sử dụng dãy lệnh sau trong hàm `setup()`:

```cpp
uint16_t calData[] = {3865, 3870, 3874, 239, 343, 3850, 259, 246};
lcd.setTouchCalibrate(calData);
```

## 🚀 Lưu ý khi lập trình
- **Tốc độ SPI**: Nên giữ ở mức **20MHz** cho màn hình và **1-2.5MHz** cho cảm ứng để đảm bảo độ ổn định trên các board giá rẻ.
- **PSRAM**: Board này không có PSRAM, hãy đảm bảo tắt flag `-DBOARD_HAS_PSRAM` trong `platformio.ini` để tránh lỗi boot.
- **Hướng xoay**: Mặc định được thiết lập là **Landscape (Xoay ngang)**.

---
*Tài liệu này được tạo tự động bởi Antigravity AI để hỗ trợ việc quản lý phần cứng.*
