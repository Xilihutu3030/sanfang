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
}

// ==================== 隐患点 ====================
const hazards = {
  list: () => request('/api/hazards'),
}

// ==================== 历史记录 ====================
const history = {
  list: () => request('/api/history'),
  save: (data) => request('/api/history', 'POST', data),
}

// ==================== 应急资源 ====================
const resources = {
  statistics: () => request('/api/resources/statistics'),
  list: (type) => request(`/api/resources/${type}`),
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
}
