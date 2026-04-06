const api = require('../../utils/api')
const util = require('../../utils/util')

Page({
  data: {
    result: null,
    recordId: '',
    saveTime: '',
    riskClass: 'risk-low',
    riskInfo: {},
    mainRisks: [],
    top5: [],
    flood: {},
    suggestions: [],
    leaderReport: '',
  },

  onLoad(options) {
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
      recordId: result.id || '',
      saveTime: result.save_time || result['研判时间'] || '',
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
    const level = this.data.riskInfo['等级'] || '研判记录'
    return {
      title: `【三防研判】${level} - ${this.data.saveTime}`,
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

  goChat() {
    wx.navigateTo({ url: '/pages/chat/chat' })
  },

  async deleteRecord() {
    const confirmed = await util.confirm('确认删除', '删除后无法恢复，确定删除该记录？')
    if (!confirmed) return

    const id = this.data.recordId
    if (!id) {
      util.showToast('无法删除')
      return
    }

    util.showLoading('删除中...')
    try {
      await api.history.delete(id)
      util.hideLoading()
      util.showToast('已删除')
      setTimeout(() => { wx.navigateBack() }, 800)
    } catch (e) {
      util.hideLoading()
      util.showToast('删除失败')
    }
  },
})
