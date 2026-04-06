/**
 * 三防系统 - API 封装
 * 统一管理所有后端接口调用
 */

const app = getApp()

// 默认配置
const DEFAULT_CONFIG = {
  timeout: 30000,      // 默认超时30秒
  retryCount: 1,       // 默认重试1次
  retryDelay: 1000,    // 重试延迟1秒
}

function getBase() {
  return app.globalData.apiBase
}

/**
 * 延迟函数
 */
function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * 统一请求封装（带超时和重试）
 * @param {string} url 接口路径
 * @param {string} method 请求方法
 * @param {object} data 请求数据
 * @param {object} options 额外配置 {timeout, retryCount}
 */
function request(url, method, data, options = {}) {
  const { timeout, retryCount } = { ...DEFAULT_CONFIG, ...options }
  
  const doRequest = (retriesLeft) => {
    // 自动附加 token
    const header = { 'Content-Type': 'application/json' }
    const token = wx.getStorageSync('sf_token')
    if (token) header['Authorization'] = 'Bearer ' + token

    return new Promise((resolve, reject) => {
      const requestTask = wx.request({
        url: getBase() + url,
        method: method || 'GET',
        data: data,
        timeout: timeout,
        header: header,
        success(res) {
          // 401 -> 跳转登录
          if (res.statusCode === 401) {
            wx.removeStorageSync('sf_token')
            wx.removeStorageSync('sf_user')
            wx.redirectTo({ url: '/pages/login/login' })
            reject({ status: 401, data: res.data })
            return
          }
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(res.data)
          } else {
            reject({ status: res.statusCode, data: res.data })
          }
        },
        fail(err) {
          reject(err)
        },
      })
    }).catch(async (err) => {
      if (retriesLeft > 0 && (!err.status || err.status >= 500)) {
        console.log(`请求失败，${retriesLeft}次重试后重新请求...`)
        await delay(DEFAULT_CONFIG.retryDelay)
        return doRequest(retriesLeft - 1)
      }
      throw err
    })
  }

  return doRequest(retryCount)
}

/**
 * 文件上传封装
 */
function uploadFile(url, filePath, name, options = {}) {
  const { timeout, formData } = { ...DEFAULT_CONFIG, ...options }
  
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: getBase() + url,
      filePath: filePath,
      name: name || 'file',
      timeout: timeout,
      formData: formData || {},
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(JSON.parse(res.data))
        } else {
          reject({ status: res.statusCode, data: res.data })
        }
      },
      fail(err) {
        reject(err)
      },
    })
  })
}

// ==================== 气象 ====================
const weather = {
  get: () => request('/api/weather'),
  refresh: () => request('/api/weather/refresh', 'POST'),
}

// ==================== 智能研判 ====================
const judge = {
  run: (data) => request('/api/ai/judge', 'POST', data),
  report: (data) => request('/api/ai/report', 'POST', data),
  responseReport: (data) => request('/api/ai/response-report', 'POST', data),
}

// ==================== 隐患点 ====================
const hazards = {
  list: (region, centerLat, centerLng, bbox) => {
    let params = []
    if (region) params.push('region=' + encodeURIComponent(region))
    if (centerLat) params.push('center_lat=' + centerLat)
    if (centerLng) params.push('center_lng=' + centerLng)
    if (bbox) {
      params.push('sw_lat=' + bbox.sw_lat)
      params.push('sw_lng=' + bbox.sw_lng)
      params.push('ne_lat=' + bbox.ne_lat)
      params.push('ne_lng=' + bbox.ne_lng)
    }
    return request('/api/hazards' + (params.length ? '?' + params.join('&') : ''))
  },
  aiAnalyze: (data) => request('/api/hazards/ai-analyze', 'POST', data, { timeout: 30000 }),
}

// ==================== 历史记录 ====================
const history = {
  list: () => request('/api/history'),
  save: (data) => request('/api/history', 'POST', data),
  delete: (id) => request(`/api/history/${id}`, 'DELETE'),
  compare: (rain24h, rain1h) => request(`/api/history/compare?rain_24h=${rain24h}&rain_1h=${rain1h}`),
}

// ==================== 应急资源 ====================
const resources = {
  statistics: (regionCode) => request('/api/resources/statistics' + (regionCode ? '?region_code=' + regionCode : '')),
  subtypes: () => request('/api/resources/subtypes'),
  list: (type, regionCode) => request(`/api/resources/${type}` + (regionCode ? '?region_code=' + regionCode : '')),
  add: (type, data) => request(`/api/resources/${type}`, 'POST', data),
  update: (type, id, data) => request(`/api/resources/${type}/${id}`, 'PUT', data),
  delete: (type, id) => request(`/api/resources/${type}/${id}`, 'DELETE'),
  import: (type, filePath) => uploadFile(`/api/resources/import/${type}`, filePath, 'file'),
  templateUrl: (type) => getBase() + `/api/resources/template/${type}`,
  recognize: (type, filePath, fileType) => uploadFile(
    '/api/resources/ai-recognize', filePath, 'file',
    { timeout: 60000, formData: { resource_type: type, file_type: fileType || 'image' } }
  ),
}

// ==================== AI智能对话 ====================
const chat = {
  send: (message, context, sessionId) => request('/api/ai/chat', 'POST', {
    message,
    context: context || undefined,
    session_id: sessionId || undefined,
  }),
}

// ==================== 潮汐/海洋数据 ====================
const tide = {
  full: (lat, lng) => request('/api/tide?lat=' + lat + '&lng=' + lng),
  marine: (lat, lng) => request('/api/tide/marine?lat=' + lat + '&lng=' + lng),
  predict: (lat, lng) => request('/api/tide/predict?lat=' + lat + '&lng=' + lng),
}

// ==================== 地形高程 ====================
const terrain = {
  elevation: (lat, lng) => request('/api/terrain/elevation?lat=' + lat + '&lng=' + lng),
  demGrid: (bounds, gridSize) => request('/api/terrain/dem-grid', 'POST', { bounds: bounds, grid_size: gridSize || 8 }),
}

// ==================== 认证 ====================
const auth = {
  tenants: () => request('/api/auth/tenants'),
  login: (tenant_id, username, password) => request('/api/auth/login', 'POST', { tenant_id, username, password }),
  me: () => request('/api/auth/me'),
  changePassword: (old_password, new_password) => request('/api/auth/password', 'POST', { old_password, new_password }),
}

// ==================== 情景推演 ====================
const simulate = {
  run: (data) => request('/api/simulate', 'POST', data),
}

// ==================== 任务派单 ====================
const tasks = {
  list: (status) => request('/api/tasks' + (status ? '?status=' + status : '')),
  batch: (data) => request('/api/tasks/batch', 'POST', data),
  assign: (id, data) => request(`/api/tasks/${id}/assign`, 'POST', data),
  feedback: (id, data) => request(`/api/tasks/${id}/feedback`, 'POST', data),
  logs: (id) => request(`/api/tasks/${id}/logs`),
}

// ==================== 在岗人员 ====================
const staff = {
  onDuty: () => request('/api/staff?on_duty=1'),
}

// ==================== 水位监测 ====================
const water = {
  stations: () => request('/api/water/stations'),
}

// ==================== 预警规则 ====================
const alerts = {
  rules: () => request('/api/alerts/rules'),
  addRule: (data) => request('/api/alerts/rules', 'POST', data),
  deleteRule: (id) => request(`/api/alerts/rules/${id}`, 'DELETE'),
}

// ==================== 自定义风险点 ====================
const customHazards = {
  list: () => request('/api/custom-hazards'),
  add: (data) => request('/api/custom-hazards', 'POST', data),
  delete: (id) => request(`/api/custom-hazards/${id}`, 'DELETE'),
}

// ==================== 视频监控 ====================
const cameras = {
  list: (params) => {
    let url = '/api/cameras?'
    if (params) {
      if (params.city) url += 'city=' + encodeURIComponent(params.city) + '&'
      if (params.type) url += 'type=' + encodeURIComponent(params.type) + '&'
    }
    return request(url)
  },
  add: (data) => request('/api/cameras', 'POST', data),
  update: (id, data) => request(`/api/cameras/${id}`, 'PUT', data),
  delete: (id) => request(`/api/cameras/${id}`, 'DELETE'),
}

// ==================== 行政区域 ====================
const regions = {
  provinces: () => request('/api/regions/provinces'),
  children: (code) => request('/api/regions/children/' + code),
  boundary: (code, full, simplify) => request('/api/regions/boundary/' + code + '?full=' + (full ? '1' : '0') + '&simplify=' + (simplify ? '1' : '0')),
  search: (q) => request('/api/regions/search?q=' + encodeURIComponent(q)),
  info: (code) => request('/api/regions/info/' + code),
  geocode: (q) => request('/api/regions/geocode?q=' + encodeURIComponent(q)),
}

// ==================== 灾情上报 ====================
const reports = {
  list: (params) => {
    let url = '/api/reports?'
    if (params) {
      if (params.type) url += 'type=' + encodeURIComponent(params.type) + '&'
      if (params.status) url += 'status=' + encodeURIComponent(params.status) + '&'
      if (params.hours) url += 'hours=' + params.hours + '&'
    }
    return request(url)
  },
  get: (id) => request(`/api/reports/${id}`),
  create: (data) => request('/api/reports', 'POST', data),
  update: (id, data) => request(`/api/reports/${id}`, 'PUT', data),
  delete: (id) => request(`/api/reports/${id}`, 'DELETE'),
  upvote: (id) => request(`/api/reports/${id}/upvote`, 'POST'),
  upload: (filePath) => uploadFile('/api/reports/upload', filePath, 'file', { timeout: 60000 }),
  summary: (hours) => request(`/api/reports/summary?hours=${hours || 6}`),
}

module.exports = {
  request,
  uploadFile,
  auth,
  weather,
  judge,
  hazards,
  history,
  resources,
  chat,
  tide,
  terrain,
  simulate,
  tasks,
  staff,
  water,
  alerts,
  customHazards,
  cameras,
  regions,
  reports,
}
