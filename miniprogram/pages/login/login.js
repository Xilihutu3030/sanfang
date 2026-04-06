const api = require('../../utils/api')

Page({
  data: {
    tenants: [],
    tenantIndex: 0,
    username: '',
    password: '',
    loading: false,
    errorMsg: '',
  },

  onLoad() {
    // 已登录则直接跳走
    const token = wx.getStorageSync('sf_token')
    if (token) {
      this._goHome()
      return
    }
    this._loadTenants()
  },

  async _loadTenants() {
    try {
      const list = await api.auth.tenants()
      this.setData({ tenants: list })
    } catch (e) {
      this.setData({ tenants: [{ id: 'demo', name: '演示单位' }] })
    }
  },

  onTenantChange(e) {
    this.setData({ tenantIndex: e.detail.value })
  },

  onUsernameInput(e) {
    this.setData({ username: e.detail.value })
  },

  onPasswordInput(e) {
    this.setData({ password: e.detail.value })
  },

  async doLogin() {
    const { tenants, tenantIndex, username, password } = this.data
    if (!username.trim() || !password) {
      this.setData({ errorMsg: '请输入用户名和密码' })
      return
    }

    const tenant = tenants[tenantIndex] || { id: 'demo' }
    this.setData({ loading: true, errorMsg: '' })

    try {
      const res = await api.auth.login(tenant.id, username.trim(), password)
      // 存储 token 和用户信息
      wx.setStorageSync('sf_token', res.token)
      wx.setStorageSync('sf_user', res.user)
      // 更新全局
      const app = getApp()
      app.globalData.token = res.token
      app.globalData.user = res.user

      wx.showToast({ title: '登录成功', icon: 'success' })
      setTimeout(() => this._goHome(), 800)
    } catch (err) {
      const msg = (err && err.data && err.data.error) || '登录失败，请检查网络'
      this.setData({ errorMsg: msg, loading: false })
    }
  },

  _goHome() {
    wx.switchTab({ url: '/pages/index/index' })
  },

  fillDemo(e) {
    const role = e.currentTarget.dataset.role
    const accounts = {
      admin: { username: 'admin', password: 'admin123' },
      operator: { username: 'operator', password: '123456' },
      viewer: { username: 'viewer', password: '123456' },
    }
    const acc = accounts[role]
    if (acc) {
      this.setData({ username: acc.username, password: acc.password, errorMsg: '' })
    }
  },
})
