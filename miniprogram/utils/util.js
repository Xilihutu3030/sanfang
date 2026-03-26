/**
 * 三防系统 - 工具函数
 */

const config = require('./config')

// ==================== 日期时间格式化 ====================

/**
 * 格式化日期时间（完整格式）
 * @param {Date|string} date
 * @returns {string} 如：2024-01-15 09:30:00
 */
function formatTime(date) {
  if (typeof date === 'string') date = new Date(date)
  const y = date.getFullYear()
  const m = (date.getMonth() + 1).toString().padStart(2, '0')
  const d = date.getDate().toString().padStart(2, '0')
  const h = date.getHours().toString().padStart(2, '0')
  const min = date.getMinutes().toString().padStart(2, '0')
  const s = date.getSeconds().toString().padStart(2, '0')
  return `${y}-${m}-${d} ${h}:${min}:${s}`
}

/**
 * 格式化时间（仅时分）
 * @param {Date} date
 * @returns {string} 如：09:30
 */
function formatTimeShort(date) {
  if (!date) date = new Date()
  if (typeof date === 'string') date = new Date(date)
  const h = date.getHours().toString().padStart(2, '0')
  const min = date.getMinutes().toString().padStart(2, '0')
  return `${h}:${min}`
}

/**
 * 格式化日期（仅日期）
 * @param {Date|string} date
 * @returns {string} 如：2024-01-15
 */
function formatDate(date) {
  if (typeof date === 'string') date = new Date(date)
  const y = date.getFullYear()
  const m = (date.getMonth() + 1).toString().padStart(2, '0')
  const d = date.getDate().toString().padStart(2, '0')
  return `${y}-${m}-${d}`
}

// ==================== 风险等级处理 ====================

/**
 * 风险等级 → 样式类名
 */
function riskClass(level) {
  if (!level) return 'risk-low'
  for (const [key, val] of Object.entries(config.RISK_LEVELS)) {
    if (level.includes(key)) return val.class
  }
  return 'risk-low'
}

/**
 * 风险等级 → 颜色
 */
function riskColor(level) {
  if (!level) return '#2563eb'
  for (const [key, val] of Object.entries(config.RISK_LEVELS)) {
    if (level.includes(key)) return val.color
  }
  return '#2563eb'
}

// ==================== 预警等级处理 ====================

/**
 * 预警等级文本 → 数字等级
 * @param {string} text 预警等级文本
 * @returns {number} 0-4
 */
function parseWarningLevel(text) {
  if (!text) return 0
  for (const [key, val] of Object.entries(config.WARNING_LEVELS)) {
    if (text.includes(key)) return val.level
  }
  return 0
}

// ==================== 气象数据处理 ====================

/**
 * 解析气象API返回数据为统一格式
 * @param {object} data 原始API数据
 * @returns {object} 统一格式的气象数据
 */
function parseWeatherData(data) {
  const info = data['综合研判'] || data || {}
  return {
    warning: info['预警等级'] || '暂无预警',
    rain1h: info['当前雨量_1h'] || '--',
    rain24h: info['累计雨量_24h'] || '--',
    forecast6h: info['未来6h预报'] || '--',
    updateTime: data.update_time || '--',
  }
}

// ==================== UI 提示 ====================

/**
 * 显示加载提示
 */
function showLoading(title) {
  wx.showLoading({ title: title || '加载中...', mask: true })
}

function hideLoading() {
  wx.hideLoading()
}

/**
 * 提示消息
 */
function showToast(title, icon) {
  wx.showToast({ title, icon: icon || 'none', duration: 2000 })
}

/**
 * 确认对话框（Promise 封装）
 * @param {string} title 标题
 * @param {string} content 内容
 * @returns {Promise<boolean>} 用户是否确认
 */
function confirm(title, content) {
  return new Promise((resolve) => {
    wx.showModal({
      title,
      content,
      success: (res) => resolve(res.confirm),
    })
  })
}

/**
 * 复制文本到剪贴板
 */
function copyText(text) {
  wx.setClipboardData({
    data: text,
    success() {
      wx.showToast({ title: '已复制', icon: 'success' })
    },
  })
}

// ==================== 定位相关 ====================

/**
 * 获取当前GPS位置
 * @returns {Promise<{lat: number, lng: number}>}
 */
function getCurrentLocation() {
  return new Promise((resolve, reject) => {
    wx.getLocation({
      type: 'gcj02',
      success: (res) => {
        resolve({
          lat: parseFloat(res.latitude.toFixed(6)),
          lng: parseFloat(res.longitude.toFixed(6)),
        })
      },
      fail: reject,
    })
  })
}

/**
 * 地图选点
 * @returns {Promise<{lat: number, lng: number, name: string, address: string}>}
 */
function chooseLocation() {
  return new Promise((resolve, reject) => {
    wx.chooseLocation({
      success: (res) => {
        resolve({
          lat: parseFloat(res.latitude.toFixed(6)),
          lng: parseFloat(res.longitude.toFixed(6)),
          name: res.name || '',
          address: res.address || '',
        })
      },
      fail: reject,
    })
  })
}

// ==================== 数据处理 ====================

/**
 * 生成唯一ID
 * @returns {string}
 */
function generateId() {
  return Date.now() + '_' + Math.random().toString(36).slice(2, 6)
}

/**
 * 判断点是否在多边形内（射线法）
 * @param {number} lat 纬度
 * @param {number} lng 经度
 * @param {Array<{latitude: number, longitude: number}>} polygon 多边形顶点
 * @returns {boolean}
 */
function pointInPolygon(lat, lng, polygon) {
  let inside = false
  const n = polygon.length
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = polygon[i].longitude, yi = polygon[i].latitude
    const xj = polygon[j].longitude, yj = polygon[j].latitude
    const intersect = ((yi > lat) !== (yj > lat)) &&
      (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi)
    if (intersect) inside = !inside
  }
  return inside
}

/**
 * 计算多边形中心点
 * @param {Array<{latitude: number, longitude: number}>} points
 * @returns {{lat: number, lng: number}}
 */
function polygonCenter(points) {
  if (!points || points.length === 0) return { lat: 0, lng: 0 }
  const lats = points.map(p => p.latitude)
  const lngs = points.map(p => p.longitude)
  return {
    lat: (Math.max(...lats) + Math.min(...lats)) / 2,
    lng: (Math.max(...lngs) + Math.min(...lngs)) / 2,
  }
}

module.exports = {
  // 日期时间
  formatTime,
  formatTimeShort,
  formatDate,
  // 风险等级
  riskClass,
  riskColor,
  // 预警等级
  parseWarningLevel,
  // 气象数据
  parseWeatherData,
  // UI 提示
  showLoading,
  hideLoading,
  showToast,
  confirm,
  copyText,
  // 定位
  getCurrentLocation,
  chooseLocation,
  // 数据处理
  generateId,
  pointInPolygon,
  polygonCenter,
}
