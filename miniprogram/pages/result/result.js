const api = require('../../utils/api')
const util = require('../../utils/util')

Page({
  data: {
    result: null,
    riskClass: 'risk-low',
    riskInfo: {},
    mainRisks: [],
    top5: [],
    flood: {},
    suggestions: [],
    leaderReport: '',
  },

  onLoad() {
    const app = getApp()
    const result = app.globalData.lastJudgeResult
    if (!result) {
      util.showToast('无研判数据')
      wx.navigateBack()
      return
    }

    const riskInfo = result['1_综合风险等级'] || {}
    this.setData({
      result,
      riskClass: util.riskClass(riskInfo['等级']),
      riskInfo,
      mainRisks: result['2_主要风险类型'] || [],
      top5: result['3_Top5危险点位'] || [],
      flood: result['4_淹没预判'] || {},
      suggestions: result['5_指挥建议'] || [],
      leaderReport: result['6_领导汇报'] || '',
    })
  },

  onShareAppMessage() {
    const level = this.data.riskInfo['等级'] || '研判结果'
    return {
      title: `【三防研判】${level} - ${util.formatTime(new Date())}`,
      path: '/pages/index/index',
    }
  },

  copyReport() {
    const text = this.data.result['简报文本'] || this.data.leaderReport
    if (text) {
      util.copyText(text)
    } else {
      util.showToast('暂无简报')
    }
  },

  copyLeaderReport() {
    if (this.data.leaderReport) {
      util.copyText(this.data.leaderReport)
    }
  },

  async saveHistory() {
    util.showLoading('保存中...')
    try {
      await api.history.save(this.data.result)
      util.hideLoading()
      util.showToast('已保存')
    } catch (e) {
      util.hideLoading()
      util.showToast('保存失败')
    }
  },

  shareResult() {
    // 触发微信分享
  },

  goChat() {
    wx.navigateTo({ url: '/pages/chat/chat' })
  },
})
