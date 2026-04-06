const api = require('../../utils/api')
const util = require('../../utils/util')

Page({
  data: {
    resourceStats: null,
    version: 'v2.0',
    userInfo: {},
    roleNames: {
      admin: '系统管理员',
      manager: '管理员',
      operator: '指挥员',
      viewer: '查看者',
    },
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 3 })
    }
    const app = getApp()
    const user = app.globalData.user || wx.getStorageSync('sf_user') || {}
    this.setData({ userInfo: user })
    this.loadStats()
  },

  async loadStats() {
    try {
      const data = await api.resources.statistics()
      this.setData({ resourceStats: data })
    } catch (e) {
      console.error('加载统计失败', e)
    }
  },

  goResources() {
    wx.switchTab({ url: '/pages/resources/resources' })
  },

  changePassword() {
    wx.showModal({
      title: '修改密码',
      editable: true,
      placeholderText: '请输入新密码（至少6位）',
      success: async (res) => {
        if (!res.confirm || !res.content) return
        const newPwd = res.content.trim()
        if (newPwd.length < 6) {
          util.showToast('密码至少6位')
          return
        }
        // 先询问旧密码
        wx.showModal({
          title: '验证旧密码',
          editable: true,
          placeholderText: '请输入旧密码',
          success: async (res2) => {
            if (!res2.confirm || !res2.content) return
            try {
              await api.auth.changePassword(res2.content, newPwd)
              util.showToast('密码修改成功')
            } catch (e) {
              const msg = (e && e.data && e.data.error) || '修改失败'
              util.showToast(msg)
            }
          }
        })
      }
    })
  },

  about() {
    wx.showModal({
      title: '关于系统',
      content: '三防应急处置指挥决策辅助系统\n微信小程序版 v2.0\n\n核心能力：\n- AI智能风险研判\n- 应急资源管理\n- 一键生成研判简报\n- 多用户账号管理',
      showCancel: false,
    })
  },

  clearCache() {
    wx.showModal({
      title: '清除缓存',
      content: '清除本地缓存数据？（不影响服务端数据和登录状态）',
      success(res) {
        if (res.confirm) {
          // 保留登录信息
          const token = wx.getStorageSync('sf_token')
          const user = wx.getStorageSync('sf_user')
          wx.clearStorageSync()
          if (token) wx.setStorageSync('sf_token', token)
          if (user) wx.setStorageSync('sf_user', user)
          util.showToast('缓存已清除')
        }
      },
    })
  },

  doLogout() {
    wx.showModal({
      title: '退出登录',
      content: '确定退出当前账号？',
      success(res) {
        if (res.confirm) {
          getApp().logout()
        }
      },
    })
  },
})
