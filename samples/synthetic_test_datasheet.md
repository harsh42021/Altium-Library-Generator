# Sample MCU Datasheet (Synthetic Test)

## 5.1 Pin Description

| Pin Number | Pin Name | Type | Structure | Description |
|---|---|---|---|---|
| 1 | VDD | Power | - | Digital supply |
| 2 | VSS | Power | - | Ground |
| 3 | NRST | I/O | Open-drain | Reset, active low |
| 4 | PA5 | I/O | Push-pull | GPIO / SPI1_SCK |
| 5 | PA6 | I/O | Push-pull | GPIO / SPI1_MISO |
| 6 | PA7 | I/O | Push-pull | GPIO / SPI1_MOSI |
| 7 | PA4 | I/O | Push-pull | GPIO / SPI1_NSS |
| 8 | PB6 | I/O | Open-drain | GPIO / I2C1_SCL |
| 9 | PB7 | I/O | Open-drain | GPIO / I2C1_SDA |
| 10 | PA9 | I/O | Push-pull | GPIO / USART1_TX |
| 11 | PA10 | I/O | Input | GPIO / USART1_RX |
| 12 | PA11 | I/O | Analog | USB_DM |
| 13 | PA12 | I/O | Analog | USB_DP |
| 14 | VDDA | Power | - | Analog supply |
| 15 | VSSA | Power | - | Analog ground |
| 16 | TCK | Input | - | JTAG clock |
| 17 | TMS | Input | - | JTAG mode select |
| 18 | TDI | Input | - | JTAG data in |
| 19 | TDO | Output | Push-pull | JTAG data out |
| 20 | PC13 | I/O | Push-pull | GPIO |
| 21 | PC14 | I/O | Push-pull | GPIO / OSC32_IN |
| 22 | PC15 | I/O | Push-pull | GPIO / OSC32_OUT |
| 23 | NC | - | - | No connect |

## 5.2 Alternate Function Mapping

| Pin | AF0 | AF1 | AF7 |
|---|---|---|---|
| PA5 | GPIO | - | SPI1_SCK |
| PA6 | GPIO | - | SPI1_MISO |
| PA7 | GPIO | - | SPI1_MOSI |
| PA9 | GPIO | - | USART1_TX |
| PA10 | GPIO | - | USART1_RX |
