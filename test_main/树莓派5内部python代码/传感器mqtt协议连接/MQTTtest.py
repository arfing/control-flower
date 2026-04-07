#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 文件名：mqtt2.py
# 功能：使用 MQTT 连接 OneNET，上报 DHT11 温湿度、土壤湿度、超声波距离、雨滴状态，接收继电器控制指令
# 说明：已改用 gpiozero 库控制继电器，避免 RPi.GPIO 在树莓派 5 上的兼容问题

import json
import time
import board
import adafruit_dht
import smbus2
from gpiozero import DigitalOutputDevice, DistanceSensor, DigitalInputDevice  # 新增 DistanceSensor, DigitalInputDevice
import paho.mqtt.client as mqtt
from datetime import datetime

# ==================== 配置区====================
DEVICE_NAME = "PIF_2"          # 设备名称
PRODUCT_ID = "r2mlq6P5sr"             # 产品ID
#  token（请确保未过期）
TOKEN = "version=2018-10-31&res=products%2Fr2mlq6P5sr%2Fdevices%2FPIF_2&et=1781764383&method=md5&sign=EQj5s85hhRtnRMcFQ5cA1g%3D%3D"
# MQTT 服务器地址 (OneNET Studio)
MQTT_SERVER = "studio-mqtt.heclouds.com"
MQTT_PORT = 1883  

# 继电器配置
RELAY_PIN = 17
# 低电平触发
RELAY_ACTIVE_HIGH = False

# 传感器配置
DHT_PIN = board.D4
dht_sensor = adafruit_dht.DHT11(DHT_PIN, use_pulseio=False)

# PCF8591 配置 (土壤湿度)
PCF8591_ADDR = 0x48
SOIL_CHANNEL = 0
bus = smbus2.SMBus(1)

# 超声波传感器配置 (HC-SR04)
TRIG_PIN = 27
ECHO_PIN = 26
ultrasonic = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=4.0)  # 最大距离4米

# 雨滴传感器配置 (数字输出)
RAIN_PIN = 25
rain_sensor = DigitalInputDevice(RAIN_PIN, pull_up=False)  # 假设传感器输出高电平表示有雨

# ==============================================================

# ---------- 初始化继电器 ----------
relay = DigitalOutputDevice(
    pin=RELAY_PIN,
    active_high=RELAY_ACTIVE_HIGH,
    initial_value=False  # 初始为断开状态
)
print(f"继电器已初始化，引脚 GPIO{RELAY_PIN}，触发逻辑：{'高电平' if RELAY_ACTIVE_HIGH else '低电平'}")

# ---------- 传感器读取函数 ----------
def read_dht11_with_retry(max_retries=3, delay_seconds=2):
    """安全地读取DHT11传感器，自带重试机制"""
    for attempt in range(max_retries):
        try:
            temperature = dht_sensor.temperature
            humidity = dht_sensor.humidity
            if (temperature is not None and humidity is not None and
                0 <= humidity <= 100 and -40 <= temperature <= 80):
                print(f"✅ DHT11第{attempt+1}次读取成功: {temperature:.1f}°C, {humidity:.1f}%")
                return temperature, humidity
            else:
                print(f"⚠️ DHT11第{attempt+1}次读取到无效数据，重试...")
        except RuntimeError as e:
            error_msg = str(e)
            if 'busy' in error_msg.lower():
                print(f"🔌 DHT11第{attempt+1}次读取失败：GPIO引脚繁忙，等待释放...")
            else:
                print(f"⚠️ DHT11第{attempt+1}次读取失败 (RuntimeError): {error_msg}")
        except Exception as e:
            print(f"❌ DHT11第{attempt+1}次读取发生意外错误: {e}")
        time.sleep(delay_seconds)
    print("❌ DHT11读取失败，跳过温湿度数据")
    return None, None

def read_soil_moisture():
    """读取土壤湿度原始值并映射为0-100%"""
    try:
        # 每次读取时打开总线
        bus = smbus2.SMBus(1)
        bus.write_byte(PCF8591_ADDR, 0x40 | SOIL_CHANNEL)
        time.sleep(0.1)
        bus.read_byte(PCF8591_ADDR)  # 丢弃第一次
        value = bus.read_byte(PCF8591_ADDR)
        bus.close()  # 关闭总线
        # 映射...
        soil_percent = 100 - int(value * 100 / 255)
        soil_percent = max(0, min(100, soil_percent))
        print(f"✅ 土壤湿度原始值: {value}, 映射后: {soil_percent}%")
        return soil_percent
    except Exception as e:
        print(f"❌ 读取土壤湿度失败: {e}")
        return None

def read_distance():
    """读取超声波距离（单位：厘米）"""
    try:
        # 读取距离（gpiozero 返回米）
        distance_m = ultrasonic.distance
        distance_cm = distance_m * 100
        print(f"✅ 超声波距离: {distance_cm:.1f} cm")
        return round(distance_cm, 1)
    except Exception as e:
        print(f"❌ 读取超声波距离失败: {e}")
        return None

def read_rain():
    """读取雨滴传感器状态，返回 1（有雨）或 0（无雨）"""
    try:
        # 假设传感器输出高电平表示有雨，低电平表示无雨
        # 如果实际逻辑相反，请修改判断条件
        if rain_sensor.is_active:
            print("✅ 雨滴传感器: 无雨水")
            return 0
        else:
            print("✅ 雨滴传感器: 检测到雨水")
            return 1
    except Exception as e:
        print(f"❌ 读取雨滴传感器失败: {e}")
        return None

# ---------- 继电器控制函数 ----------
def process_command(cmd):
    """解析并执行从云端下发的指令"""
    if "relay" in cmd:
        state = cmd["relay"]
        if state == 1:
            relay.on()
            print("💡 继电器已打开")
        elif state == 0:
            relay.off()
            print("💡 继电器已关闭")
        else:
            print(f"⚠️ 未知继电器状态: {state}")
    else:
        print(f"⚠️ 未知命令格式: {cmd}")

# ---------- MQTT 回调函数 ----------
def on_connect(client, userdata, flags, rc):
    """连接成功后的回调"""
    if rc == 0:
        print("✅ 成功连接到 OneNET MQTT 服务器")
        # 订阅属性设置主题（接收指令）
        cmd_topic = f"$sys/{PRODUCT_ID}/{DEVICE_NAME}/thing/property/set"
        client.subscribe(cmd_topic)
        print(f"已订阅主题: {cmd_topic}")
    else:
        print(f"❌ 连接失败，错误码: {rc}")

def on_message(client, userdata, msg):
    """收到消息的回调"""
    payload_str = msg.payload.decode('utf-8')
    print(f"📩 收到指令: {msg.topic} -> {payload_str}")

    try:
        data = json.loads(payload_str)
        # 解析指令，例如 {"params": {"relay": {"value": 1}}} 或 {"params": {"relay": 1}}
        if "params" in data and "relay" in data["params"]:
            relay_info = data["params"]["relay"]
            if isinstance(relay_info, dict):
                relay_value = relay_info.get("value")
            else:
                relay_value = relay_info
            process_command({"relay": relay_value})
    except json.JSONDecodeError:
        print("⚠️ 无法解析指令 JSON")
    except Exception as e:
        print(f"指令处理出错: {e}")

def on_disconnect(client, userdata, rc):
    """断开连接后的回调"""
    print("⚠️ 与 MQTT 服务器断开连接")

# ---------- 数据上报函数 ----------
def publish_property(temperature, humidity, soil_moisture, distance, rain):
    """上报属性到 OneNET"""
    topic = f"$sys/{PRODUCT_ID}/{DEVICE_NAME}/thing/property/post"

    params = {}
    if temperature is not None:
        params["CurrentTemperature"] = {"value": round(temperature)}
    if humidity is not None:
        params["CurrentHumidity"] = {"value": round(humidity)}
    if soil_moisture is not None:
        params["SoilMoisture"] = {"value": soil_moisture}
    if distance is not None:
        params["Distance"] = {"value": distance}  # 新增距离属性
    if rain is not None:
        params["RainDetected"] = {"value": rain == 1}  # 新增雨滴状态

    payload = {
        "id": str(int(time.time() * 1000)),
        "version": "1.0",
        "params": params
    }

    payload_json = json.dumps(payload)
    result = client.publish(topic, payload_json)
    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        print(f"📤 数据上报成功到 {topic}")
    else:
        print(f"❌ 数据上报失败，错误码: {result.rc}")

# ---------- 主程序 ----------
def main():
    global client
    print("=" * 50)
    print("MQTT 传感器上报与继电器控制 (gpiozero 版)")
    print("=" * 50)

    # 创建 MQTT 客户端
    client = mqtt.Client(client_id=DEVICE_NAME, protocol=mqtt.MQTTv311)
    client.username_pw_set(PRODUCT_ID, TOKEN)  # 设置用户名和密码

    # 绑定回调函数
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    try:
        # 连接到服务器
        client.connect(MQTT_SERVER, MQTT_PORT, keepalive=60)
        # 启动网络循环（新线程）
        client.loop_start()

        # 主循环：定期读取传感器并上报
        while True:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{current_time}] 开始采集...")

            # 读取传感器
            temperature, humidity = read_dht11_with_retry()
            soil_moisture = read_soil_moisture()
            distance = read_distance()
            rain = read_rain()

            # 上报数据
            if client.is_connected():
                publish_property(temperature, humidity, soil_moisture, distance, rain)
            else:
                print("⚠️ MQTT 未连接，尝试重连...")
                client.reconnect()

            # 传感器间隔（DHT11 需要至少 2 秒）
            time.sleep(2)

    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"程序运行出错: {e}")
    finally:
        client.loop_stop()
        client.disconnect()
        dht_sensor.exit()
        # gpiozero 会自动清理，无需额外调用
        print("资源已清理")

if __name__ == "__main__":
    main()