import cv2
import numpy as np
import onnxruntime as ort
import time
import threading
from flask import Flask, Response, render_template, jsonify, request
from flask_cors import CORS
from picamera2 import Picamera2
from libcamera import controls
import config

# PCA9685 舵机控制
import board
import busio
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo

# 初始化 I2C 总线
i2c = busio.I2C(board.SCL, board.SDA)
pca = PCA9685(i2c)
pca.frequency = 50  # 舵机标准频率 50Hz

# 创建两个舵机对象，分别连接在通道 0 和通道 1
servo0 = servo.Servo(pca.channels[0], min_pulse=500, max_pulse=2500)  # 通道0
servo1 = servo.Servo(pca.channels[1], min_pulse=500, max_pulse=2500)  # 通道1

app = Flask(__name__)
CORS(app)

# ---------- 全局变量 ----------
latest_frame = None
latest_fps = 0.0
conf_thres = config.CONFIDENCE_THRESHOLD
running = True

# 跳帧参数
INFERENCE_INTERVAL = 2
JPEG_QUALITY = 75
last_detections = []

# ---------- 摄像头初始化 ----------
def init_camera():
    picam2 = Picamera2()
    config_cam = picam2.create_preview_configuration(main={"format": 'RGB888', "size": (640, 480)})
    picam2.configure(config_cam)
    picam2.start()
    try:
        picam2.set_controls({"AfMode": controls.AfModeEnum.Continuous})
        print("已启用连续自动对焦")
    except:
        pass
    time.sleep(1)
    return picam2

# ---------- 模型加载 ----------
def load_model():
    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_options.intra_op_num_threads = 2
    session = ort.InferenceSession(config.MODEL_PATH, sess_options, providers=['CPUExecutionProvider'])
    input_name = session.get_inputs()[0].name
    return session, input_name

# ---------- 预处理 ----------
def preprocess(image, input_size):
    h, w = image.shape[:2]
    scale = min(input_size / h, input_size / w)
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized = cv2.resize(image, (new_w, new_h))
    canvas = np.full((input_size, input_size, 3), 114, dtype=np.uint8)
    canvas[:new_h, :new_w] = resized
    img = canvas.transpose(2, 0, 1).astype(np.float32) / 255.0
    return img, scale, (new_w, new_h)

# ---------- 后处理 ----------
def postprocess(outputs, scale, pad, orig_shape, conf_thres, iou_thres):
    out = outputs[0]
    if out.shape[1] == 5 + len(config.CLASS_NAMES):
        predictions = out.squeeze(0).T
    elif out.shape[2] == 5 + len(config.CLASS_NAMES):
        predictions = out.squeeze(0)
    else:
        predictions = out.squeeze(0)
        if predictions.shape[1] > predictions.shape[0]:
            predictions = predictions.T

    scores = predictions[:, 4]
    mask = scores > conf_thres
    predictions = predictions[mask]
    if len(predictions) == 0:
        return []

    class_scores = predictions[:, 5:]
    class_ids = np.argmax(class_scores, axis=1)
    confs = class_scores[np.arange(len(class_ids)), class_ids] * predictions[:, 4]

    boxes = predictions[:, :4]
    boxes[:, 0] = (boxes[:, 0] - boxes[:, 2] / 2) / scale
    boxes[:, 1] = (boxes[:, 1] - boxes[:, 3] / 2) / scale
    boxes[:, 2] = (boxes[:, 0] + boxes[:, 2] / scale)
    boxes[:, 3] = (boxes[:, 1] + boxes[:, 3] / scale)

    indices = cv2.dnn.NMSBoxes(boxes.tolist(), confs.tolist(), conf_thres, iou_thres)
    if len(indices) > 0:
        return [(boxes[i], confs[i], class_ids[i]) for i in indices.flatten()]
    else:
        return []

# ---------- 主处理线程 ----------
def process_frames():
    global latest_frame, latest_fps, conf_thres, last_detections
    picam2 = init_camera()
    session, input_name = load_model()
    print("推理线程启动")

    frame_count = 0
    prev_gray = None

    while running:
        frame_rgb = picam2.capture_array()
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

        # 运动检测（可选）
        motion = True
        if config.MOTION_THRESHOLD > 0:
            gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            if prev_gray is not None:
                delta = cv2.absdiff(prev_gray, gray)
                thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
                thresh = cv2.dilate(thresh, None, iterations=2)
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                motion = any(cv2.contourArea(cnt) > config.MOTION_THRESHOLD for cnt in contours)
            prev_gray = gray

        # 跳帧推理
        if motion and (frame_count % INFERENCE_INTERVAL == 0):
            start = time.time()
            input_tensor, scale, _ = preprocess(frame_rgb, config.INPUT_SIZE)
            input_tensor = np.expand_dims(input_tensor, axis=0).astype(np.float32)

            outputs = session.run(None, {input_name: input_tensor})
            inference_time = time.time() - start
            latest_fps = 1.0 / inference_time if inference_time > 0 else 0

            last_detections = postprocess(outputs, scale, None, frame_rgb.shape[:2],
                                          conf_thres, config.IOU_THRESHOLD)

        # 绘制检测框
        for box, conf, cls_id in last_detections:
            if cls_id < len(config.CLASS_NAMES):
                x1, y1, x2, y2 = map(int, box)
                label = f"{config.CLASS_NAMES[cls_id]}: {conf:.2f}"
                cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame_bgr, label, (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)

        # 显示 FPS
        cv2.putText(frame_bgr, f"FPS: {latest_fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

        latest_frame = frame_bgr
        frame_count += 1
        time.sleep(0.03)

    picam2.stop()
    print("推理线程结束")

# ---------- 启动后台线程 ----------
thread = threading.Thread(target=process_frames, daemon=True)
thread.start()

# ---------- Flask 路由 ----------
def generate_frames():
    while running:
        if latest_frame is not None:
            ret, jpeg = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        time.sleep(0.03)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def get_status():
    return jsonify({"fps": latest_fps})

@app.route('/api/conf_thres', methods=['POST'])
def set_conf_thres():
    global conf_thres
    data = request.get_json()
    if 'value' in data:
        conf_thres = data['value']
        return jsonify({"status": "ok"})
    return jsonify({"error": "invalid"}), 400

# ---------- 双舵机控制接口（PCA9685） ----------
@app.route('/api/servo', methods=['POST'])
def set_servo():
    """控制舵机，请求体 JSON 格式：
       {"channel": 0, "angle": 90}  或 {"channel": 1, "angle": 120}
       角度范围 0~180
    """
    data = request.get_json()
    if 'channel' not in data or 'angle' not in data:
        return jsonify({"error": "缺少 channel 或 angle 参数"}), 400

    channel = data['channel']
    angle = data['angle']

    # 验证 channel
    if channel not in (0, 1):
        return jsonify({"error": "channel 必须为 0 或 1"}), 400

    try:
        angle = float(angle)
    except ValueError:
        return jsonify({"error": "angle 必须为数字"}), 400

    if angle < 0 or angle > 180:
        return jsonify({"error": "角度范围 0~180"}), 400

    try:
        if channel == 0:
            servo0.angle = angle
        else:
            servo1.angle = angle
        return jsonify({"status": "ok", "channel": channel, "angle": angle})
    except Exception as e:
        return jsonify({"error": f"控制失败: {e}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)