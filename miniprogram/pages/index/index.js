const api = require('../../utils/api')
const util = require('../../utils/util')

Page({
  data: {
    weather: null,
    lastJudge: null,
    resourceStats: null,
    loading: false,
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 0 })
    }
    this.loadWeather()
    this.loadResourceStats()
    // 如果有缓存的研判结果
    const app = getApp()
    if (app.globalData.lastJudgeResult) {
      this.setData({ lastJudge: app.globalData.lastJudgeResult })
    }
  },

  onPullDownRefresh() {
    this.loadWeather()
    this.loadResourceStats()
    wx.stopPullDownRefresh()
  },

  async loadWeather() {
    try {
      const data = await api.weather.get()
      this.setData({ weather: util.parseWeatherData(data) })
      getApp().globalData.weatherData = data
    } catch (e) {
      console.error('获取气象数据失败', e)
    }
  },

  async loadResourceStats() {
    try {
      const data = await api.resources.statistics()
      this.setData({ resourceStats: data })
    } catch (e) {
      console.error('获取资源统计失败', e)
    }
  },

  goJudge() {
    wx.navigateTo({ url: '/pages/judge/judge' })
  },

  goHistory() {
    wx.switchTab({ url: '/pages/history/history' })
  },

  goResources() {
    wx.switchTab({ url: '/pages/resources/resources' })
  },

  async refreshWeather() {
    util.showLoading('正在刷新...')
    try {
      const data = await api.weather.refresh()
      this.setData({ weather: util.parseWeatherData(data) })
      util.hideLoading()
      util.showToast('气象已刷新')
    } catch (e) {
      util.hideLoading()
      util.showToast('刷新失败')
    }
  },

  viewLastResult() {
    if (this.data.lastJudge) {
      getApp().globalData.lastJudgeResult = this.data.lastJudge
      wx.navigateTo({ url: '/pages/result/result' })
    }
  },

  goPage(e) {
    wx.navigateTo({ url: e.currentTarget.dataset.url })
  },
})
