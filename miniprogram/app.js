App({
  globalData: {
    // 后端服务地址：自动区分开发/生产环境
    // 上线前将 YOUR_DOMAIN 替换为你的实际域名
    apiBase: __wxConfig.envVersion === 'release'
      ? 'https://YOUR_DOMAIN'
      : 'http://localhost:5000',
    // 缓存的天气数据
    weatherData: null,
    // 最近一次研判结果
    lastJudgeResult: null,
    // AI识别预填数据（跨页面传递）
    aiPrefillData: null,
    // 认证信息
    token: null,
    user: null,
  },

  onLaunch() {
    console.log('三防智能研判系统启动');
    // 恢复登录状态
    const token = wx.getStorageSync('sf_token')
    const user = wx.getStorageSync('sf_user')
    if (token) {
      this.globalData.token = token
      this.globalData.user = user
    }
  },

  /** 检查是否已登录，未登录则跳转 */
  checkAuth() {
    if (!this.globalData.token) {
      wx.redirectTo({ url: '/pages/login/login' })
      return false
    }
    return true
  },

  /** 退出登录 */
  logout() {
    this.globalData.token = null
    this.globalData.user = null
    wx.removeStorageSync('sf_token')
    wx.removeStorageSync('sf_user')
    wx.redirectTo({ url: '/pages/login/login' })
  },
})
