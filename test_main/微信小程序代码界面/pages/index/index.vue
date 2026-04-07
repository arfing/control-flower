<template>
	<view class="container">
		<!-- 标题 -->
		<view class="header">
			<text class="title">🌱 智能花卉管理系统</text>
			<text class="subtitle">实时数据 · 一键控制</text>
		</view>

		<!-- 数据卡片 -->
		<view class="data-card">
			<view class="data-item">
				<text class="data-label">🌡️ 温度</text>
				<text class="data-value">{{temp}} ℃</text>
			</view>
			<view class="data-item">
				<text class="data-label">💧 湿度</text>
				<text class="data-value">{{humi}} %</text>
			</view>
			<view class="data-item">
				<text class="data-label">🪴 土壤湿度</text>
				<text class="data-value">{{SoilMoisture}} %</text>
			</view>
			<!-- 新增距离 -->
			<view class="data-item">
				<text class="data-label">📏 植株高度</text>
				<text class="data-value">{{distance}} cm</text>
			</view>
			<!-- 新增雨滴状态 -->
			<view class="data-item">
				<text class="data-label">🌧️ 雨滴状态</text>
				<text class="data-value">{{rainText}}</text>
			</view>
		</view>

		<!-- 继电器控制卡片（改进部分） -->
		<view class="control-card">
			<!-- 模式切换按钮组 -->
			<view class="mode-switch">
				<view 
					class="mode-btn" 
					:class="{ active: mode === 'manual' }"
					@click="switchMode('manual')"
				>🖐️ 手动</view>
				<view 
					class="mode-btn" 
					:class="{ active: mode === 'auto' }"
					@click="switchMode('auto')"
				>🤖 自动</view>
			</view>

			<!-- 手动模式：显示开关 -->
			<view v-if="mode === 'manual'" class="control-row">
				<view class="control-left">
					<text class="control-label">⚙️ 继电器水泵</text>
					<text class="control-status">{{ relay ? '开启' : '关闭' }}</text>
				</view>
				<switch :checked="relay" @change="onrelaySwitch" color="#07C160" />
			</view>

			<!-- 自动模式：阈值控制 -->
			<view v-else class="auto-panel">
				<!-- 阈值设置行 -->
				<view class="threshold-row">
					<text class="threshold-label">🌊 土壤阈值</text>
					<view class="threshold-input-wrapper">
						<input 
							type="number" 
							v-model.number="threshold" 
							min="0" max="100" step="1"
							class="threshold-input"
							@change="onThresholdChange"
						/>
						<text class="threshold-unit">%</text>
					</view>
				</view>
				<!-- 自动状态说明 -->
				<view class="auto-info">
					<text class="info-text">
						当前土壤湿度 {{SoilMoisture}}% 
						<span v-if="SoilMoisture < threshold">🌧️ 低于阈值，水泵应开启</span>
						<span v-else>☀️ 高于阈值，水泵应关闭</span>
					</text>
					<text class="relay-state">当前水泵实际状态: {{ relay ? '开启' : '关闭' }}</text>
				</view>
				<!-- 自动模式下禁用开关（仅用于显示状态） -->
				<view class="fake-switch">
					<text class="fake-label">自动控制中</text>
					<switch :checked="relay" disabled color="#07C160" />
				</view>
			</view>
		</view>

		<!-- 底部留白 -->
		<view class="footer"></view>
	</view>
</template>

<script>
	const { createCommonToken } = require('@/key.js')
	
	export default {
		data() {
			return {
				temp: '',
				humi: '',
				SoilMoisture: '',
				distance: '',        // 新增：超声波距离（cm）
				rain: 0,             // 新增：雨滴状态（0=无雨，1=有雨）
				relay: false,
				token: '',
				mode: 'manual',
				threshold: 40,
				timer: null,
			}
		},
		computed: {
			// 根据 rain 值显示文本
			rainText() {
				if (this.rain === 1) return '有雨 🌧️';
				if (this.rain === 0) return '无雨 ☀️';
				return '--';
			}
		},
		onLoad() {
			const params = {
				author_key: '203ef76d40da41b4a3282d9b1ce4cd8d',
				version: '2022-05-01',
				user_id: '465373'
			}
			this.token = createCommonToken(params);
			this.fetchDevData();
		},
		
		onShow() {
			this.timer = setInterval(() => {
				this.fetchDevData();
			}, 3000);
		},
		
		onHide() {
			if (this.timer) {
				clearInterval(this.timer);
				this.timer = null;
			}
		},
		
		onUnload() {
			if (this.timer) {
				clearInterval(this.timer);
				this.timer = null;
			}
		},
		
		methods: {
			// 获取设备数据（优化为按标识符匹配）
			fetchDevData() {
			    uni.request({
			        url: 'https://iot-api.heclouds.com/thingmodel/query-device-property',
			        method: 'GET',
			        data: {
			            product_id: 'r2mlq6P5sr',
			            device_name: 'PIF_2'
			        },
			        header: {
			            'authorization': this.token
			        },
			        success: (res) => {
			            console.log('获取数据成功', res.data);
			            const dataList = res.data.data || [];
			            
			            // 根据标识符匹配属性值
			            const findValue = (identifier) => {
			                const item = dataList.find(d => d.identifier === identifier);
			                return item ? item.value : null;
			            };
			            
			            // 传感器数据（无论模式如何，都正常更新）
			            this.humi = findValue('CurrentHumidity') ?? '--';
			            this.temp = findValue('CurrentTemperature') ?? '--';
			            this.SoilMoisture = findValue('SoilMoisture') ?? '--';
			            this.distance = findValue('Distance') ?? '--';
			            
			            // 雨滴状态处理
			            let rainVal = findValue('RainDetected');
			            if (rainVal !== null && rainVal !== undefined) {
			                if (typeof rainVal === 'boolean') {
			                    this.rain = rainVal ? 1 : 0;
			                } else if (typeof rainVal === 'string') {
			                    this.rain = (rainVal.toLowerCase() === 'true') ? 1 : 0;
			                } else {
			                    this.rain = Number(rainVal);
			                    if (isNaN(this.rain)) this.rain = null;
			                }
			            } else {
			                this.rain = null;
			            }
			            
			            // ----- 关键修改：继电器状态只在自动模式下更新 -----
			            if (this.mode === 'auto') {
			                let relayVal = findValue('relay');
			                if (relayVal !== null && relayVal !== undefined) {
			                    if (typeof relayVal === 'boolean') {
			                        this.relay = relayVal;
			                    } else if (typeof relayVal === 'string') {
			                        this.relay = relayVal.toLowerCase() === 'true';
			                    } else {
			                        this.relay = Boolean(relayVal);
			                    }
			                }
			                // 自动模式下还需要执行一次自动控制（可选，但建议保留）
			                this.autoControl();
			            } else {
			                // 手动模式下，继电器状态保持用户上次操作，不覆盖
			                console.log('手动模式，保持继电器状态:', this.relay);
			                // 注意：这里不执行 autoControl()
			            }
			            // ------------------------------------------------
			        },
			        fail: (err) => {
			            console.error('获取数据失败', err);
			        }
			    });
			},
			
			// 手动切换继电器
			onrelaySwitch(event) {
				const value = event.detail.value;
				this.relay = value;
				this.setRelayState(value);
			},
			
			// 发送继电器状态
			setRelayState(state) {
				uni.request({
					url: 'https://iot-api.heclouds.com/thingmodel/set-device-property',
					method: 'POST',
					data: {
						product_id: 'r2mlq6P5sr',
						device_name: 'PIF_2',
						params: { "relay": state }
					},
					header: {
						'authorization': this.token
					},
					success: () => {
						console.log('设置继电器成功', state);
					},
					fail: (err) => {
						console.error('设置继电器失败', err);
					}
				});
			},
			
			// 切换模式
			switchMode(mode) {
				this.mode = mode;
				if (mode === 'auto') {
					this.autoControl();
				}
			},
			
			// 阈值变更
			onThresholdChange() {
				if (this.threshold < 0) this.threshold = 0;
				if (this.threshold > 100) this.threshold = 100;
				if (this.mode === 'auto') {
					this.autoControl();
				}
			},
			
			// 自动控制逻辑（基于土壤湿度）
			autoControl() {
				console.log('当前模式：', this.mode)
				if (this.mode !== 'auto') return;
				const soil = Number(this.SoilMoisture);
				const th = Number(this.threshold);
				if (isNaN(soil) || isNaN(th)) return;
				const shouldOpen = soil < th;
				if (shouldOpen !== this.relay) {
					console.log(`自动控制: 土壤湿度${soil}% 阈值${th}%，切换继电器至${shouldOpen ? '开启' : '关闭'}`);
					this.relay = shouldOpen;
					this.setRelayState(shouldOpen);
				}
			}
		}
	}
</script>

<style scoped>
	/* 原有样式保持不变，新增的 data-item 已自动适配 */
	.container {
		min-height: 100vh;
		background: linear-gradient(145deg, #f5f7fa 0%, #e9ecf2 100%);
		padding: 40rpx 30rpx;
		box-sizing: border-box;
		font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
	}

	.header {
		margin-bottom: 40rpx;
	}
	.title {
		font-size: 48rpx;
		font-weight: 700;
		color: #2c3e50;
		display: block;
		letter-spacing: 1px;
	}
	.subtitle {
		font-size: 28rpx;
		color: #7f8c8d;
		margin-top: 8rpx;
		display: block;
	}

	.data-card {
		background-color: #ffffff;
		border-radius: 32rpx;
		padding: 30rpx;
		margin-bottom: 30rpx;
		box-shadow: 0 20rpx 40rpx rgba(0, 0, 0, 0.05);
	}
	.data-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 24rpx 0;
		border-bottom: 1rpx solid #f0f0f0;
	}
	.data-item:last-child {
		border-bottom: none;
	}
	.data-label {
		font-size: 32rpx;
		color: #34495e;
		font-weight: 500;
	}
	.data-value {
		font-size: 40rpx;
		font-weight: 600;
		color: #1abc9c;
		background-color: #e8f8f5;
		padding: 8rpx 32rpx;
		border-radius: 50rpx;
	}

	.control-card {
		background-color: #ffffff;
		border-radius: 32rpx;
		padding: 30rpx;
		box-shadow: 0 20rpx 40rpx rgba(0, 0, 0, 0.05);
	}
	.mode-switch {
		display: flex;
		background-color: #f0f2f5;
		border-radius: 60rpx;
		padding: 6rpx;
		margin-bottom: 30rpx;
	}
	.mode-btn {
		flex: 1;
		text-align: center;
		padding: 16rpx 0;
		font-size: 28rpx;
		font-weight: 500;
		border-radius: 60rpx;
		color: #7f8c8d;
		transition: all 0.2s;
	}
	.mode-btn.active {
		background-color: #1abc9c;
		color: white;
		box-shadow: 0 4rpx 12rpx rgba(26, 188, 156, 0.3);
	}
	.control-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 10rpx 0;
	}
	.control-left {
		display: flex;
		align-items: center;
	}
	.control-label {
		font-size: 34rpx;
		font-weight: 500;
		color: #2c3e50;
		margin-right: 20rpx;
	}
	.control-status {
		font-size: 28rpx;
		color: #7f8c8d;
		background-color: #f0f0f0;
		padding: 6rpx 20rpx;
		border-radius: 40rpx;
	}
	.auto-panel {
		margin-top: 10rpx;
	}
	.threshold-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 24rpx;
		padding: 10rpx 0;
		border-bottom: 1rpx solid #f0f0f0;
	}
	.threshold-label {
		font-size: 32rpx;
		color: #34495e;
		font-weight: 500;
	}
	.threshold-input-wrapper {
		display: flex;
		align-items: center;
		background-color: #f8f9fa;
		border-radius: 50rpx;
		padding: 8rpx 24rpx;
		border: 1rpx solid #e0e0e0;
	}
	.threshold-input {
		width: 100rpx;
		text-align: center;
		font-size: 32rpx;
		font-weight: 600;
		color: #1abc9c;
		background: transparent;
	}
	.threshold-unit {
		font-size: 28rpx;
		color: #95a5a6;
		margin-left: 6rpx;
	}
	.auto-info {
		background-color: #f8f9fa;
		border-radius: 24rpx;
		padding: 20rpx;
		margin-bottom: 24rpx;
	}
	.info-text {
		font-size: 26rpx;
		color: #2c3e50;
		display: block;
		margin-bottom: 8rpx;
	}
	.relay-state {
		font-size: 26rpx;
		color: #7f8c8d;
		display: block;
	}
	.fake-switch {
		display: flex;
		justify-content: space-between;
		align-items: center;
		opacity: 0.8;
	}
	.fake-label {
		font-size: 30rpx;
		color: #7f8c8d;
	}
	switch {
		transform: scale(0.9);
	}
	.footer {
		height: 20rpx;
	}
</style>