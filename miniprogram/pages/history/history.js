const api = require('../../utils/api')
const util = require('../../utils/util')

Page({
  data: {
    list: [],
    loading: false,
  },

  onShow() {
    this.loadHistory()
  },

  onPullDownRefresh() {
    this.loadHistory()
    wx.stopPullDownRefresh()
  },

  async loadHistory() {
    this.setData({ loading: true })
    try {
      const list = await api.history.list()
      // 添加风险样式类
      const processed = (Array.isArray(list) ? list : []).map((item) => {
        const riskInfo = item['1_综合风险等级'] || {}
        return {
          ...item,
          _riskClass: util.riskClass(riskInfo['等级']),
          _riskLevel: riskInfo['等级'] || '--',
          _riskScore: riskInfo['得分'] || '--',
          _time: item['save_time'] || item['研判时间'] || '--',
        }
      })
      this.setData({ list: processed, loading: false })
    } catch (e) {
      this.setData({ loading: false })
      console.error('加载历史失败', e)
    }
  },

  viewDetail(e) {
    const idx = e.currentTarget.dataset.idx
    const item = this.data.list[idx]
    if (item) {
      getApp().globalData.lastJudgeResult = item
      wx.navigateTo({ url: '/pages/result/result' })
    }
  },
})
